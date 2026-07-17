from garage_sales.application import (
    GetSalesInsightsUseCase,
    GetTopProductsUseCase,
    RepositorySalesQueryExecutor,
    SalesInsightSynthesizer,
    SalesQueryPlanner,
)
from garage_sales.config import RelationalDatabaseSettings
from garage_sales.domain.ports import RelationalPersistence
from garage_sales.infrastructure.sqlalchemy.database import SqlAlchemyRelationalPersistence


def build_relational_persistence(
    settings: RelationalDatabaseSettings | None = None,
) -> SqlAlchemyRelationalPersistence:
    active_settings = settings or RelationalDatabaseSettings.from_env()
    return SqlAlchemyRelationalPersistence(active_settings.url, echo=active_settings.echo)


def build_get_sales_insights(
    *,
    relational_persistence: RelationalPersistence,
    planner: SalesQueryPlanner,
    synthesizer: SalesInsightSynthesizer,
) -> GetSalesInsightsUseCase:
    """Compose the use case without choosing an LLM or an inbound adapter."""

    return GetSalesInsightsUseCase(
        planner=planner,
        query_executor=RepositorySalesQueryExecutor(relational_persistence),
        synthesizer=synthesizer,
    )


def build_get_top_products(
    *,
    relational_persistence: RelationalPersistence,
) -> GetTopProductsUseCase:
    """Compose the deterministic use case with the active repositories."""

    return GetTopProductsUseCase(relational_persistence=relational_persistence)
