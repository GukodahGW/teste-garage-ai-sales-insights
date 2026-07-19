import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import SecretStr

from garage_sales.adapters.langchain import (
    GemmaJobApiError,
    GemmaJobChatModel,
    GemmaJobTimeoutError,
    UnsupportedLlmProviderError,
    build_chat_model,
)
from garage_sales.adapters.langchain.chat_models import APPLICATION_USER_AGENT
from garage_sales.config import LlmProviderSettings


def _settings(**overrides: Any) -> LlmProviderSettings:
    values: dict[str, Any] = {
        "provider": "gemma",
        "base_url": "https://gemma.example.com/v1/",
        "model": "gemma-test.gguf",
        "api_key": "provider-secret",
        "timeout_seconds": 90,
        "max_retries": 3,
        "max_tokens": 384,
        "temperature": 0,
        "enable_thinking": False,
    }
    values.update(overrides)
    return LlmProviderSettings(**values)


def _succeeded_job(*, content: str = "READY") -> dict[str, Any]:
    return {
        "id": "job_0123456789abcdef0123456789abcdef",
        "object": "inference.job",
        "status": "succeeded",
        "attempts": 1,
        "max_attempts": 5,
        "response": {
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "model": "gemma-test.gguf",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 12,
                "completion_tokens": 3,
                "total_tokens": 15,
            },
        },
    }


def _model_with_transport(
    handler: Callable[[httpx.Request], httpx.Response],
    **overrides: Any,
) -> tuple[GemmaJobChatModel, httpx.Client]:
    model = build_chat_model(_settings(**overrides))
    assert isinstance(model, GemmaJobChatModel)
    client = httpx.Client(transport=httpx.MockTransport(handler))
    model._http_client = client
    model._sleep = lambda _delay: None
    return model, client


def test_build_chat_model_configures_durable_gemma_job_api() -> None:
    model = build_chat_model(_settings())

    assert isinstance(model, GemmaJobChatModel)
    assert model.base_url == "https://gemma.example.com/v1"
    assert isinstance(model.api_key, SecretStr)
    assert model.api_key.get_secret_value() == "provider-secret"
    assert model.model_name == "gemma-test.gguf"
    assert model.max_tokens == 384
    assert model.timeout_seconds == 90
    assert model.max_retries == 3
    assert model.enable_thinking is False


def test_chat_model_submits_and_long_polls_a_completion_job() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.headers["Authorization"] == "Bearer provider-secret"
        assert request.headers["User-Agent"] == APPLICATION_USER_AGENT
        if request.method == "POST":
            body = json.loads(request.content)
            assert request.url.path == "/v1/jobs"
            assert request.headers["Idempotency-Key"]
            assert body == {
                "model": "gemma-test.gguf",
                "messages": [
                    {"role": "system", "content": "Follow instructions."},
                    {"role": "user", "content": "Reply READY."},
                ],
                "temperature": 0.0,
                "max_tokens": 384,
                "stream": False,
                "chat_template_kwargs": {"enable_thinking": False},
            }
            return httpx.Response(
                202,
                json={
                    "id": "job_0123456789abcdef0123456789abcdef",
                    "status": "queued",
                    "attempts": 0,
                },
            )
        assert request.method == "GET"
        assert request.url.path.endswith("/wait")
        assert request.url.params["timeout"] == "20.000s"
        return httpx.Response(200, json=_succeeded_job())

    model, client = _model_with_transport(handler)
    try:
        result = model.invoke(
            [SystemMessage("Follow instructions."), HumanMessage("Reply READY.")]
        )
    finally:
        client.close()

    assert isinstance(result, AIMessage)
    assert result.content == "READY"
    assert result.id == "chatcmpl-test"
    assert result.response_metadata["finish_reason"] == "stop"
    assert result.response_metadata["job_id"] == "job_0123456789abcdef0123456789abcdef"
    assert result.usage_metadata == {
        "input_tokens": 12,
        "output_tokens": 3,
        "total_tokens": 15,
    }
    assert [request.method for request in requests] == ["POST", "GET"]


def test_submission_retry_reuses_the_same_idempotency_key() -> None:
    submission_keys: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            submission_keys.append(request.headers["Idempotency-Key"])
            if len(submission_keys) == 1:
                return httpx.Response(
                    503,
                    json={"error": {"code": "busy", "message": "try again"}},
                )
            return httpx.Response(
                202,
                json={
                    "id": "job_0123456789abcdef0123456789abcdef",
                    "status": "queued",
                    "attempts": 0,
                },
            )
        return httpx.Response(200, json=_succeeded_job())

    model, client = _model_with_transport(handler)
    try:
        assert model.invoke("hello").content == "READY"
    finally:
        client.close()

    assert len(submission_keys) == 2
    assert submission_keys[0] == submission_keys[1]


def test_terminal_job_failure_is_exposed_without_polling_forever() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(
                202,
                json={
                    "id": "job_0123456789abcdef0123456789abcdef",
                    "status": "queued",
                    "attempts": 0,
                },
            )
        return httpx.Response(
            200,
            json={
                "id": "job_0123456789abcdef0123456789abcdef",
                "status": "failed",
                "attempts": 5,
                "error": {"code": "inference_timeout", "message": "deadline exceeded"},
            },
        )

    model, client = _model_with_transport(handler)
    try:
        with pytest.raises(GemmaJobApiError, match="inference_timeout"):
            model.invoke("hello")
    finally:
        client.close()


def test_job_is_canceled_when_the_end_to_end_deadline_expires() -> None:
    methods: list[str] = []
    clock_value = -0.1

    def clock() -> float:
        nonlocal clock_value
        clock_value += 0.1
        return clock_value

    def handler(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        return httpx.Response(
            202 if request.method == "POST" else 200,
            json={
                "id": "job_0123456789abcdef0123456789abcdef",
                "status": "queued" if request.method != "DELETE" else "canceled",
                "attempts": 0,
            },
        )

    model, client = _model_with_transport(handler, timeout_seconds=0.5)
    model._clock = clock
    try:
        with pytest.raises(GemmaJobTimeoutError, match="0.5 segundos"):
            model.invoke("hello")
    finally:
        client.close()

    assert methods[-1] == "DELETE"


def test_build_chat_model_rejects_the_discarded_openai_compatible_provider() -> None:
    settings = _settings(provider="openai-compatible")

    with pytest.raises(UnsupportedLlmProviderError, match="openai-compatible"):
        build_chat_model(settings)
