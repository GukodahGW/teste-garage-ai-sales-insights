import time
from collections.abc import Callable, Sequence
from typing import Any, cast
from uuid import uuid4

import httpx
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    UsageMetadata,
    convert_to_openai_messages,
)
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import ConfigDict, Field, PrivateAttr, SecretStr

from garage_sales.config import LlmProviderSettings

APPLICATION_USER_AGENT = "garage-sales-insights/0.1"
_ACTIVE_JOB_STATUSES = frozenset({"queued", "running", "retrying"})
_TERMINAL_JOB_STATUSES = frozenset({"succeeded", "failed", "canceled", "expired"})
_TRANSIENT_HTTP_STATUSES = frozenset({408, 425, 429})
_LONG_POLL_SECONDS = 20.0


class UnsupportedLlmProviderError(ValueError):
    """Raised when the composition root requests an unknown LLM provider."""


class GemmaJobApiError(RuntimeError):
    """Raised when the durable Gemma job API cannot return a completion."""


class GemmaJobTimeoutError(GemmaJobApiError, TimeoutError):
    """Raised after the configured end-to-end job deadline."""


class _GemmaJobApiClient:
    def __init__(
        self,
        *,
        http_client: httpx.Client,
        base_url: str,
        api_key: str,
        timeout_seconds: float,
        max_retries: int,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._http_client = http_client
        self._jobs_url = f"{base_url.rstrip('/')}/jobs"
        self._headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {api_key}",
            "User-Agent": APPLICATION_USER_AGENT,
        }
        self._timeout_seconds = timeout_seconds
        self._max_retries = max_retries
        self._clock = clock
        self._sleep = sleep

    def complete(self, request_body: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        deadline = self._clock() + self._timeout_seconds
        idempotency_key = uuid4().hex
        job_id: str | None = None
        terminal = False
        try:
            submission = self._request(
                "POST",
                self._jobs_url,
                deadline=deadline,
                headers={**self._headers, "Idempotency-Key": idempotency_key},
                json=request_body,
            )
            self._require_status(submission, 202, "submeter o job")
            job = self._response_object(submission, "submissao do job")
            job_id = self._required_string(job, "id", "submissao do job")

            while True:
                status = self._required_string(job, "status", f"job {job_id}")
                terminal = status in _TERMINAL_JOB_STATUSES
                if status == "succeeded":
                    response = job.get("response")
                    if not isinstance(response, dict):
                        raise GemmaJobApiError(
                            f"job Gemma {job_id} concluido sem uma resposta de completion valida"
                        )
                    return cast(dict[str, Any], response), job
                if terminal:
                    raise self._terminal_error(job_id, status, job)
                if status not in _ACTIVE_JOB_STATUSES:
                    raise GemmaJobApiError(
                        f"job Gemma {job_id} retornou status desconhecido: {status}"
                    )

                remaining = self._remaining(deadline)
                wait_seconds = min(_LONG_POLL_SECONDS, remaining)
                poll = self._request(
                    "GET",
                    f"{self._jobs_url}/{job_id}/wait",
                    deadline=deadline,
                    headers=self._headers,
                    params={"timeout": f"{wait_seconds:.3f}s"},
                    request_timeout=min(remaining, wait_seconds + 5.0),
                )
                self._require_status(poll, 200, f"consultar o job {job_id}")
                job = self._response_object(poll, f"consulta do job {job_id}")
        except BaseException:
            if job_id is not None and not terminal:
                self._cancel(job_id)
            raise

    def _request(
        self,
        method: str,
        url: str,
        *,
        deadline: float,
        headers: dict[str, str],
        request_timeout: float | None = None,
        **kwargs: Any,
    ) -> httpx.Response:
        failures = 0
        while True:
            remaining = self._remaining(deadline)
            timeout = min(remaining, request_timeout or remaining)
            try:
                response = self._http_client.request(
                    method,
                    url,
                    headers=headers,
                    timeout=timeout,
                    **kwargs,
                )
            except httpx.TransportError as error:
                if failures >= self._max_retries:
                    raise GemmaJobApiError(
                        f"falha de transporte ao acessar a API de jobs Gemma: {error}"
                    ) from error
                failures += 1
                self._backoff(failures, deadline, None)
                continue

            if not self._is_transient(response.status_code) or failures >= self._max_retries:
                return response
            failures += 1
            self._backoff(failures, deadline, response)

    def _backoff(
        self,
        failure_number: int,
        deadline: float,
        response: httpx.Response | None,
    ) -> None:
        delay = min(0.25 * (2 ** (failure_number - 1)), 2.0)
        if response is not None:
            retry_after = response.headers.get("Retry-After")
            if retry_after is not None:
                try:
                    delay = min(max(float(retry_after), 0.0), 5.0)
                except ValueError:
                    pass
        remaining = self._remaining(deadline)
        if delay >= remaining:
            raise GemmaJobTimeoutError(
                f"job Gemma excedeu o limite de {self._timeout_seconds:g} segundos"
            )
        self._sleep(delay)

    def _remaining(self, deadline: float) -> float:
        remaining = deadline - self._clock()
        if remaining <= 0:
            raise GemmaJobTimeoutError(
                f"job Gemma excedeu o limite de {self._timeout_seconds:g} segundos"
            )
        return remaining

    def _cancel(self, job_id: str) -> None:
        try:
            self._http_client.request(
                "DELETE",
                f"{self._jobs_url}/{job_id}",
                headers=self._headers,
                timeout=5.0,
            )
        except httpx.HTTPError:
            pass

    @staticmethod
    def _is_transient(status_code: int) -> bool:
        return status_code in _TRANSIENT_HTTP_STATUSES or status_code >= 500

    @staticmethod
    def _response_object(response: httpx.Response, operation: str) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError as error:
            raise GemmaJobApiError(
                f"API de jobs Gemma retornou JSON invalido durante {operation}"
            ) from error
        if not isinstance(payload, dict):
            raise GemmaJobApiError(
                f"API de jobs Gemma retornou payload invalido durante {operation}"
            )
        return cast(dict[str, Any], payload)

    @classmethod
    def _require_status(
        cls,
        response: httpx.Response,
        expected: int,
        operation: str,
    ) -> None:
        if response.status_code == expected:
            return
        code = "http_error"
        message = response.reason_phrase
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if isinstance(payload, dict) and isinstance(payload.get("error"), dict):
            error = payload["error"]
            if isinstance(error.get("code"), str):
                code = error["code"]
            if isinstance(error.get("message"), str):
                message = error["message"]
        raise GemmaJobApiError(
            f"API de jobs Gemma falhou ao {operation} "
            f"(HTTP {response.status_code}, {code}): {message[:1000]}"
        )

    @staticmethod
    def _required_string(payload: dict[str, Any], field: str, operation: str) -> str:
        value = payload.get(field)
        if not isinstance(value, str) or not value.strip():
            raise GemmaJobApiError(
                f"API de jobs Gemma omitiu {field!r} durante {operation}"
            )
        return value

    @staticmethod
    def _terminal_error(job_id: str, status: str, job: dict[str, Any]) -> GemmaJobApiError:
        error = job.get("error")
        code = "job_terminal"
        message = f"job terminou com status {status}"
        if isinstance(error, dict):
            if isinstance(error.get("code"), str):
                code = error["code"]
            if isinstance(error.get("message"), str):
                message = error["message"]
        return GemmaJobApiError(
            f"job Gemma {job_id} falhou ({status}, {code}): {message[:1000]}"
        )


class GemmaJobChatModel(BaseChatModel):
    """LangChain chat model backed by the provider's durable asynchronous queue."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    model_name: str
    base_url: str
    api_key: SecretStr = Field(repr=False)
    temperature: float = 0.0
    max_tokens: int = 512
    timeout_seconds: float = 900.0
    max_retries: int = 2
    enable_thinking: bool = False

    _http_client: httpx.Client | None = PrivateAttr(default=None)
    _clock: Callable[[], float] = PrivateAttr(default=time.monotonic)
    _sleep: Callable[[float], None] = PrivateAttr(default=time.sleep)

    @property
    def _llm_type(self) -> str:
        return "gemma-durable-job-api"

    @property
    def _identifying_params(self) -> dict[str, Any]:
        return {
            "model_name": self.model_name,
            "base_url": self.base_url,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "enable_thinking": self.enable_thinking,
        }

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        del run_manager
        converted_messages = convert_to_openai_messages(messages, text_format="string")
        if not isinstance(converted_messages, list):
            raise TypeError("a requisicao Gemma exige uma lista de mensagens")
        request_body: dict[str, Any] = {
            "model": self.model_name,
            "messages": converted_messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "stream": False,
            "chat_template_kwargs": {"enable_thinking": self.enable_thinking},
        }
        if stop:
            request_body["stop"] = stop
        for name in ("response_format", "seed", "top_p"):
            if name in kwargs:
                request_body[name] = kwargs[name]

        if self._http_client is not None:
            completion, job = self._complete(self._http_client, request_body)
        else:
            with httpx.Client() as http_client:
                completion, job = self._complete(http_client, request_body)
        return _chat_result(completion, job)

    def _complete(
        self,
        http_client: httpx.Client,
        request_body: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        return _GemmaJobApiClient(
            http_client=http_client,
            base_url=self.base_url,
            api_key=self.api_key.get_secret_value(),
            timeout_seconds=self.timeout_seconds,
            max_retries=self.max_retries,
            clock=self._clock,
            sleep=self._sleep,
        ).complete(request_body)


def _chat_result(completion: dict[str, Any], job: dict[str, Any]) -> ChatResult:
    choices = completion.get("choices")
    if not isinstance(choices, Sequence) or isinstance(choices, (str, bytes)) or not choices:
        raise GemmaJobApiError("resposta Gemma nao contem choices")
    choice = choices[0]
    if not isinstance(choice, dict) or not isinstance(choice.get("message"), dict):
        raise GemmaJobApiError("resposta Gemma nao contem uma mensagem valida")
    message_payload = choice["message"]
    content = message_payload.get("content")
    if content is None and "tool_calls" in message_payload:
        content = ""
    if not isinstance(content, (str, list)):
        raise GemmaJobApiError("mensagem Gemma nao contem content valido")

    job_id = job.get("id")
    model_name = completion.get("model")
    finish_reason = choice.get("finish_reason")
    response_metadata = {
        "finish_reason": finish_reason,
        "model_name": model_name,
        "job_id": job_id,
        "job_attempts": job.get("attempts"),
    }
    additional_kwargs = {
        key: message_payload[key]
        for key in ("tool_calls", "refusal", "reasoning_content")
        if key in message_payload
    }
    usage = completion.get("usage")
    usage_metadata = _usage_metadata(usage)
    message = AIMessage(
        content=content,
        id=completion.get("id") if isinstance(completion.get("id"), str) else None,
        additional_kwargs=additional_kwargs,
        response_metadata=response_metadata,
        usage_metadata=usage_metadata,
    )
    generation_info = {"finish_reason": finish_reason}
    return ChatResult(
        generations=[ChatGeneration(message=message, generation_info=generation_info)],
        llm_output={
            "token_usage": usage if isinstance(usage, dict) else {},
            "model_name": model_name,
            "job_id": job_id,
            "job_attempts": job.get("attempts"),
        },
    )


def _usage_metadata(value: Any) -> UsageMetadata | None:
    if not isinstance(value, dict):
        return None
    input_tokens = value.get("prompt_tokens")
    output_tokens = value.get("completion_tokens")
    total_tokens = value.get("total_tokens")
    if not all(isinstance(item, int) for item in (input_tokens, output_tokens, total_tokens)):
        return None
    return UsageMetadata(
        input_tokens=cast(int, input_tokens),
        output_tokens=cast(int, output_tokens),
        total_tokens=cast(int, total_tokens),
    )


def build_chat_model(settings: LlmProviderSettings | None = None) -> BaseChatModel:
    """Build the configured LangChain model behind the BaseChatModel contract."""

    active_settings = settings or LlmProviderSettings.from_env()
    if active_settings.provider != "gemma":
        raise UnsupportedLlmProviderError(f"LLM provider nao suportado: {active_settings.provider}")
    if active_settings.api_key is None:
        raise ValueError("LLM api_key e obrigatoria para a API de jobs Gemma")

    return GemmaJobChatModel(
        model_name=active_settings.model,
        base_url=active_settings.base_url,
        api_key=SecretStr(active_settings.api_key),
        temperature=active_settings.temperature,
        max_tokens=active_settings.max_tokens,
        timeout_seconds=active_settings.timeout_seconds,
        max_retries=active_settings.max_retries,
        enable_thinking=active_settings.enable_thinking,
    )
