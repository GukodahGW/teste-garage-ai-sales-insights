import os
import re
from collections.abc import MutableMapping
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_RELATIONAL_DATABASE_URL = "sqlite+pysqlite:///./garage.db"
DEFAULT_LLM_PROVIDER = "gemma"
DEFAULT_LLM_BASE_URL = "http://127.0.0.1:8080/v1"
DEFAULT_LLM_MODEL = "gemma-4-e4b-it"
DEFAULT_LLM_API_KEY = "sk-no-key-required"
_ENVIRONMENT_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def load_runtime_env(
    path: str | Path | None = None,
    *,
    environ: MutableMapping[str, str] | None = None,
) -> Path | None:
    """Load a simple dotenv file without overriding the active environment.

    When no path is supplied, ``.env`` is read from the current working directory.
    """

    target = _resolve_env_file(path)
    if target is None:
        return None

    active_environment = os.environ if environ is None else environ
    try:
        lines = target.read_text(encoding="utf-8-sig").splitlines()
    except OSError as error:
        raise ValueError(f"nao foi possivel ler o arquivo de ambiente: {target}") from error

    for line_number, source_line in enumerate(lines, start=1):
        line = source_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line.removeprefix("export ").lstrip()
        if "=" not in line:
            raise ValueError(f"linha {line_number} invalida no arquivo de ambiente")

        name, raw_value = line.split("=", 1)
        name = name.strip()
        if _ENVIRONMENT_NAME.fullmatch(name) is None:
            raise ValueError(f"nome invalido na linha {line_number} do arquivo de ambiente")
        if name in active_environment:
            continue

        active_environment[name] = _parse_env_value(
            raw_value.strip(),
            line_number=line_number,
        )
    return target


def _resolve_env_file(path: str | Path | None) -> Path | None:
    if path is not None:
        candidate = Path(path).expanduser().resolve()
        return candidate if candidate.is_file() else None

    candidate = Path.cwd() / ".env"
    return candidate.resolve() if candidate.is_file() else None


def _parse_env_value(value: str, *, line_number: int) -> str:
    if not value:
        return ""
    if value[0] not in {'"', "'"}:
        return value
    if len(value) < 2 or value[-1] != value[0]:
        raise ValueError(f"aspas invalidas na linha {line_number} do arquivo de ambiente")
    return value[1:-1]


@dataclass(frozen=True, slots=True)
class RelationalDatabaseSettings:
    url: str = DEFAULT_RELATIONAL_DATABASE_URL
    echo: bool = False

    @classmethod
    def from_env(cls, prefix: str = "GARAGE_") -> "RelationalDatabaseSettings":
        echo_value = os.getenv(f"{prefix}DATABASE_ECHO", "false").strip().lower()
        return cls(
            url=os.getenv(f"{prefix}DATABASE_URL", DEFAULT_RELATIONAL_DATABASE_URL),
            echo=echo_value in {"1", "true", "yes", "on"},
        )


@dataclass(frozen=True, slots=True)
class LlmProviderSettings:
    provider: str = DEFAULT_LLM_PROVIDER
    base_url: str = DEFAULT_LLM_BASE_URL
    model: str = DEFAULT_LLM_MODEL
    api_key: str = field(default=DEFAULT_LLM_API_KEY, repr=False)
    timeout_seconds: float = 180.0
    max_retries: int = 2
    max_tokens: int = 512
    temperature: float = 0.0
    enable_thinking: bool = False

    def __post_init__(self) -> None:
        provider = self.provider.strip().lower()
        base_url = self.base_url.strip().rstrip("/")
        model = self.model.strip()
        api_key = self.api_key.strip()
        if not provider:
            raise ValueError("LLM provider nao pode ser vazio")
        if not base_url.startswith(("http://", "https://")):
            raise ValueError("LLM base_url deve usar http ou https")
        if not model:
            raise ValueError("LLM model nao pode ser vazio")
        if not api_key:
            raise ValueError("LLM api_key nao pode ser vazia")
        if self.timeout_seconds <= 0:
            raise ValueError("LLM timeout_seconds deve ser positivo")
        if self.max_retries < 0:
            raise ValueError("LLM max_retries nao pode ser negativo")
        if self.max_tokens <= 0:
            raise ValueError("LLM max_tokens deve ser positivo")
        if not 0 <= self.temperature <= 2:
            raise ValueError("LLM temperature deve estar entre 0 e 2")
        object.__setattr__(self, "provider", provider)
        object.__setattr__(self, "base_url", base_url)
        object.__setattr__(self, "model", model)
        object.__setattr__(self, "api_key", api_key)

    @classmethod
    def from_env(cls, prefix: str = "GARAGE_") -> "LlmProviderSettings":
        api_key = os.getenv(f"{prefix}LLM_API_KEY")
        api_key_file = os.getenv(f"{prefix}LLM_API_KEY_FILE")
        if api_key and api_key_file:
            raise ValueError("configure somente LLM_API_KEY ou LLM_API_KEY_FILE")
        if api_key_file:
            try:
                api_key = Path(api_key_file).expanduser().read_text(encoding="utf-8").strip()
            except OSError as error:
                raise ValueError(f"nao foi possivel ler LLM_API_KEY_FILE: {error}") from error

        return cls(
            provider=os.getenv(f"{prefix}LLM_PROVIDER", DEFAULT_LLM_PROVIDER),
            base_url=os.getenv(f"{prefix}LLM_BASE_URL", DEFAULT_LLM_BASE_URL),
            model=os.getenv(f"{prefix}LLM_MODEL", DEFAULT_LLM_MODEL),
            api_key=api_key or DEFAULT_LLM_API_KEY,
            timeout_seconds=_float_from_env(
                f"{prefix}LLM_TIMEOUT_SECONDS",
                default=180.0,
            ),
            max_retries=_int_from_env(f"{prefix}LLM_MAX_RETRIES", default=2),
            max_tokens=_int_from_env(f"{prefix}LLM_MAX_TOKENS", default=512),
            temperature=_float_from_env(f"{prefix}LLM_TEMPERATURE", default=0.0),
            enable_thinking=_bool_from_env(
                f"{prefix}LLM_ENABLE_THINKING",
                default=False,
            ),
        )


def _bool_from_env(name: str, *, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int_from_env(name: str, *, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError as error:
        raise ValueError(f"{name} deve ser um inteiro") from error


def _float_from_env(name: str, *, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError as error:
        raise ValueError(f"{name} deve ser numerico") from error
