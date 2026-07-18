from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy.engine import URL, make_url

from garage_sales.config import RelationalDatabaseSettings, load_runtime_env

PROJECT_ROOT = Path(__file__).resolve().parents[4]


def _alembic_config(database_url: str | URL) -> Config:
    rendered_url = str(database_url)
    configuration = Config(str(PROJECT_ROOT / "alembic.ini"))
    configuration.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    configuration.attributes["database_url"] = rendered_url
    return configuration


def upgrade_database(database_url: str | URL, revision: str = "head") -> None:
    """Apply pending schema revisions to the selected relational database."""

    command.upgrade(_alembic_config(database_url), revision)


def downgrade_database(database_url: str | URL, revision: str = "-1") -> None:
    """Revert revisions explicitly requested by an operator."""

    command.downgrade(_alembic_config(database_url), revision)


def run() -> None:
    """Console entry point that migrates the database configured in the environment."""

    load_runtime_env()
    settings = RelationalDatabaseSettings.from_env()
    upgrade_database(settings.url)
    dialect = make_url(settings.url).get_backend_name()
    print(f"Migracoes aplicadas: {dialect}")


if __name__ == "__main__":
    run()
