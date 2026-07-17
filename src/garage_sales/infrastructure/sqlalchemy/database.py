from collections.abc import Mapping
from typing import Any

from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session, sessionmaker

from garage_sales.infrastructure.sqlalchemy.models import Base
from garage_sales.infrastructure.sqlalchemy.unit_of_work import (
    SqlAlchemyRelationalReadUnitOfWork,
)


class SqlAlchemyRelationalPersistence:
    """Adaptador relacional SQLAlchemy; o dialeto e selecionado pela URL."""

    def __init__(
        self,
        database_url: str | URL,
        *,
        echo: bool = False,
        engine_options: Mapping[str, Any] | None = None,
    ) -> None:
        options: dict[str, Any] = {"echo": echo, "pool_pre_ping": True}
        options.update(engine_options or {})
        self.engine: Engine = create_engine(database_url, **options)
        self.session_factory = sessionmaker(
            bind=self.engine,
            class_=Session,
            expire_on_commit=False,
        )

    def read(self) -> SqlAlchemyRelationalReadUnitOfWork:
        return SqlAlchemyRelationalReadUnitOfWork(self.session_factory)

    def create_schema(self) -> None:
        """Cria o schema para testes/demos; em producao, prefira migracoes Alembic."""
        Base.metadata.create_all(self.engine)

    def dispose(self) -> None:
        self.engine.dispose()
