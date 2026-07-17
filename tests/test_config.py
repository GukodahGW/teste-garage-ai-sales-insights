from _pytest.monkeypatch import MonkeyPatch

from garage_sales.config import DEFAULT_DATABASE_URL, DatabaseSettings


def test_database_settings_use_safe_local_default(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.delenv("GARAGE_DATABASE_URL", raising=False)
    monkeypatch.delenv("GARAGE_DATABASE_ECHO", raising=False)

    assert DatabaseSettings.from_env() == DatabaseSettings(url=DEFAULT_DATABASE_URL, echo=False)


def test_database_settings_read_the_active_adapter_url(monkeypatch: MonkeyPatch) -> None:
    database_url = "postgresql+psycopg://user:password@database/garage"
    monkeypatch.setenv("GARAGE_DATABASE_URL", database_url)
    monkeypatch.setenv("GARAGE_DATABASE_ECHO", "true")

    assert DatabaseSettings.from_env() == DatabaseSettings(url=database_url, echo=True)
