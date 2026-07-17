import pytest
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from garage_sales.adapters.langchain import (
    UnsupportedLlmProviderError,
    build_chat_model,
)
from garage_sales.adapters.langchain.chat_models import APPLICATION_USER_AGENT
from garage_sales.config import LlmProviderSettings


def test_build_chat_model_configures_openai_compatible_gemma() -> None:
    settings = LlmProviderSettings(
        provider="gemma",
        base_url="https://gemma.example.com/v1/",
        model="gemma-test",
        api_key="provider-secret",
        timeout_seconds=90,
        max_retries=3,
        max_tokens=384,
        temperature=0,
        enable_thinking=False,
    )

    model = build_chat_model(settings)

    assert isinstance(model, ChatOpenAI)
    assert model.openai_api_base == "https://gemma.example.com/v1"
    assert isinstance(model.openai_api_key, SecretStr)
    assert model.openai_api_key.get_secret_value() == "provider-secret"
    assert model.model_name == "gemma-test"
    assert model.max_tokens == 384
    assert model.max_retries == 3
    assert model.default_headers == {"User-Agent": APPLICATION_USER_AGENT}
    assert model.extra_body == {"chat_template_kwargs": {"enable_thinking": False}}
    assert model.use_responses_api is False


def test_build_chat_model_rejects_unknown_provider() -> None:
    settings = LlmProviderSettings(provider="unknown")

    with pytest.raises(UnsupportedLlmProviderError, match="unknown"):
        build_chat_model(settings)
