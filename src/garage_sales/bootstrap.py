from garage_sales.config import DatabaseSettings
from garage_sales.infrastructure.sqlalchemy.database import SqlAlchemyPersistence


def build_persistence(settings: DatabaseSettings | None = None) -> SqlAlchemyPersistence:
    active_settings = settings or DatabaseSettings.from_env()
    return SqlAlchemyPersistence(active_settings.url, echo=active_settings.echo)

