from pathlib import Path

from _pytest.monkeypatch import MonkeyPatch

from garage_sales.config import (
    DEFAULT_LLM_API_KEY,
    DEFAULT_LLM_BASE_URL,
    DEFAULT_LLM_MODEL,
    DEFAULT_LLM_PROVIDER,
    DEFAULT_RELATIONAL_DATABASE_URL,
    LlmProviderSettings,
    RelationalDatabaseSettings,
    load_runtime_env,
)


def test_load_runtime_env_reads_supported_dotenv_syntax(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        """
        # runtime configuration
        export GARAGE_LLM_PROVIDER=gemma
        GARAGE_LLM_BASE_URL="https://gemma.example.com/v1"
        GARAGE_LLM_API_KEY_FILE='cloudflare-api-key.txt'
        EMPTY_VALUE=
        """,
        encoding="utf-8",
    )
    environment: dict[str, str] = {}

    loaded_file = load_runtime_env(env_file, environ=environment)

    assert loaded_file == env_file.resolve()
    assert environment == {
        "GARAGE_LLM_PROVIDER": "gemma",
        "GARAGE_LLM_BASE_URL": "https://gemma.example.com/v1",
        "GARAGE_LLM_API_KEY_FILE": "cloudflare-api-key.txt",
        "EMPTY_VALUE": "",
    }


def test_load_runtime_env_preserves_active_environment(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("GARAGE_LLM_MODEL=model-from-file\n", encoding="utf-8")
    environment = {"GARAGE_LLM_MODEL": "model-from-process"}

    load_runtime_env(env_file, environ=environment)

    assert environment["GARAGE_LLM_MODEL"] == "model-from-process"


def test_load_runtime_env_rejects_invalid_lines_without_exposing_values(
    tmp_path: Path,
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("invalid-line-with-secret-value\n", encoding="utf-8")

    try:
        load_runtime_env(env_file, environ={})
    except ValueError as error:
        assert str(error) == "linha 1 invalida no arquivo de ambiente"
    else:
        raise AssertionError("uma linha sem separador deveria ser rejeitada")


def test_relational_database_settings_use_safe_local_default(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.delenv("GARAGE_DATABASE_URL", raising=False)
    monkeypatch.delenv("GARAGE_DATABASE_ECHO", raising=False)

    assert RelationalDatabaseSettings.from_env() == RelationalDatabaseSettings(
        url=DEFAULT_RELATIONAL_DATABASE_URL,
        echo=False,
    )


def test_relational_database_settings_read_active_adapter_url(
    monkeypatch: MonkeyPatch,
) -> None:
    database_url = "postgresql+psycopg://user:password@database/garage"
    monkeypatch.setenv("GARAGE_DATABASE_URL", database_url)
    monkeypatch.setenv("GARAGE_DATABASE_ECHO", "true")

    assert RelationalDatabaseSettings.from_env() == RelationalDatabaseSettings(
        url=database_url,
        echo=True,
    )


def test_llm_provider_settings_use_safe_local_defaults(monkeypatch: MonkeyPatch) -> None:
    for name in (
        "GARAGE_LLM_PROVIDER",
        "GARAGE_LLM_BASE_URL",
        "GARAGE_LLM_MODEL",
        "GARAGE_LLM_API_KEY",
        "GARAGE_LLM_API_KEY_FILE",
        "GARAGE_LLM_TIMEOUT_SECONDS",
        "GARAGE_LLM_MAX_RETRIES",
        "GARAGE_LLM_MAX_TOKENS",
        "GARAGE_LLM_TEMPERATURE",
        "GARAGE_LLM_ENABLE_THINKING",
    ):
        monkeypatch.delenv(name, raising=False)

    settings = LlmProviderSettings.from_env()

    assert settings == LlmProviderSettings(
        provider=DEFAULT_LLM_PROVIDER,
        base_url=DEFAULT_LLM_BASE_URL,
        model=DEFAULT_LLM_MODEL,
        api_key=DEFAULT_LLM_API_KEY,
    )
    assert DEFAULT_LLM_API_KEY not in repr(settings)


def test_llm_provider_settings_read_cloudflare_key_file(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    key_file = tmp_path / "gemma-api-key.txt"
    key_file.write_text("secret-from-file\n", encoding="utf-8")
    monkeypatch.delenv("GARAGE_LLM_API_KEY", raising=False)
    monkeypatch.setenv("GARAGE_LLM_API_KEY_FILE", str(key_file))
    monkeypatch.setenv("GARAGE_LLM_BASE_URL", "https://gemma.example.com/v1/")
    monkeypatch.setenv("GARAGE_LLM_MAX_RETRIES", "4")
    monkeypatch.setenv("GARAGE_LLM_ENABLE_THINKING", "false")

    settings = LlmProviderSettings.from_env()

    assert settings.base_url == "https://gemma.example.com/v1"
    assert settings.api_key == "secret-from-file"
    assert settings.max_retries == 4
    assert settings.enable_thinking is False


def test_llm_provider_settings_reject_two_key_sources(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("GARAGE_LLM_API_KEY", "direct-key")
    monkeypatch.setenv("GARAGE_LLM_API_KEY_FILE", "key.txt")

    try:
        LlmProviderSettings.from_env()
    except ValueError as error:
        assert "somente" in str(error)
    else:
        raise AssertionError("duas fontes de credencial deveriam ser rejeitadas")
