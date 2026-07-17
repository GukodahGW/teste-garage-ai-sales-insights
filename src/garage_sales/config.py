import os
from dataclasses import dataclass

DEFAULT_DATABASE_URL = "sqlite+pysqlite:///./garage.db"


@dataclass(frozen=True, slots=True)
class DatabaseSettings:
    url: str = DEFAULT_DATABASE_URL
    echo: bool = False

    @classmethod
    def from_env(cls, prefix: str = "GARAGE_") -> "DatabaseSettings":
        echo_value = os.getenv(f"{prefix}DATABASE_ECHO", "false").strip().lower()
        return cls(
            url=os.getenv(f"{prefix}DATABASE_URL", DEFAULT_DATABASE_URL),
            echo=echo_value in {"1", "true", "yes", "on"},
        )
