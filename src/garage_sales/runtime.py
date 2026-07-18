from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from langchain_core.language_models.chat_models import BaseChatModel

from garage_sales.adapters.http import create_app
from garage_sales.adapters.langchain import (
    LangChainSalesQueryPlanner,
    build_chat_model,
)
from garage_sales.application import DeterministicSalesInsightSynthesizer
from garage_sales.bootstrap import (
    build_get_sales_insights,
    build_get_top_products,
    build_relational_persistence,
)
from garage_sales.config import (
    LlmProviderSettings,
    RelationalDatabaseSettings,
    SalesQueryPlannerSettings,
    load_runtime_env,
)


def create_runtime_app(
    *,
    database_settings: RelationalDatabaseSettings | None = None,
    llm_settings: LlmProviderSettings | None = None,
    planner_settings: SalesQueryPlannerSettings | None = None,
    model: BaseChatModel | None = None,
) -> FastAPI:
    """Compose concrete infrastructure while preserving replaceable ports."""

    if (
        database_settings is None
        or planner_settings is None
        or (llm_settings is None and model is None)
    ):
        load_runtime_env()
    active_database_settings = database_settings or RelationalDatabaseSettings.from_env()
    active_planner_settings = planner_settings or SalesQueryPlannerSettings.from_env()
    persistence = build_relational_persistence(active_database_settings)
    active_model = model or build_chat_model(llm_settings)
    get_sales_insights = build_get_sales_insights(
        relational_persistence=persistence,
        planner=LangChainSalesQueryPlanner(
            active_model,
            max_date_validation_retries=(
                active_planner_settings.date_validation_max_retries
            ),
            max_filter_validation_retries=(
                active_planner_settings.filter_validation_max_retries
            ),
        ),
        synthesizer=DeterministicSalesInsightSynthesizer(),
    )
    get_top_products = build_get_top_products(relational_persistence=persistence)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            persistence.dispose()

    return create_app(
        get_sales_insights=get_sales_insights,
        get_top_products=get_top_products,
        lifespan=lifespan,
    )


def run() -> None:
    """Run the fully composed API from environment-backed settings."""

    load_runtime_env()
    uvicorn.run(
        "garage_sales.runtime:create_runtime_app",
        factory=True,
        host="127.0.0.1",
        port=8000,
    )
