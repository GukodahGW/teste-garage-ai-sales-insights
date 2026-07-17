from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from garage_sales.config import LlmProviderSettings

APPLICATION_USER_AGENT = "garage-sales-insights/0.1"


class UnsupportedLlmProviderError(ValueError):
    """Raised when the composition root requests an unknown LLM provider."""


def build_chat_model(settings: LlmProviderSettings | None = None) -> BaseChatModel:
    """Build the configured LangChain model behind the BaseChatModel contract."""

    active_settings = settings or LlmProviderSettings.from_env()
    if active_settings.provider not in {"gemma", "openai-compatible"}:
        raise UnsupportedLlmProviderError(f"LLM provider nao suportado: {active_settings.provider}")

    return ChatOpenAI(
        model=active_settings.model,
        base_url=active_settings.base_url,
        api_key=SecretStr(active_settings.api_key),
        temperature=active_settings.temperature,
        max_completion_tokens=active_settings.max_tokens,
        timeout=active_settings.timeout_seconds,
        max_retries=active_settings.max_retries,
        stream_usage=False,
        use_responses_api=False,
        default_headers={"User-Agent": APPLICATION_USER_AGENT},
        extra_body={
            "chat_template_kwargs": {
                "enable_thinking": active_settings.enable_thinking,
            }
        },
    )
