from typing import Annotated, TypeVar

import uvicorn
from fastapi import APIRouter, FastAPI, HTTPException, Query, status
from starlette.types import Lifespan

from garage_sales.adapters.http.schemas import (
    AnalysisCellResponse,
    AnalysisDatasetResponse,
    AnalysisRowResponse,
    ErrorResponse,
    SalesInsightResponse,
    SalesInsightsQuery,
    SalesMonthResponse,
    TopProductResponse,
    TopProductsResponse,
)
from garage_sales.application import GetSalesInsights, GetTopProducts, SalesPlanningError

T = TypeVar("T")


def _require_use_case(use_case: T | None, name: str) -> T:
    if use_case is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"O caso de uso {name} ainda nao foi configurado.",
        )
    return use_case


def _create_router(
    get_sales_insights: GetSalesInsights | None,
    get_top_products: GetTopProducts | None,
) -> APIRouter:
    router = APIRouter()

    @router.get(
        "/sales-insights",
        response_model=SalesInsightResponse,
        response_model_exclude_defaults=True,
        responses={
            status.HTTP_422_UNPROCESSABLE_CONTENT: {
                "model": ErrorResponse,
                "description": "A pergunta nao produziu um plano analitico seguro.",
            },
            status.HTTP_503_SERVICE_UNAVAILABLE: {
                "model": ErrorResponse,
                "description": "Caso de uso ainda nao conectado ao adapter HTTP.",
            },
        },
        summary="Consulta vendas em linguagem natural",
        tags=["sales"],
    )
    def sales_insights(
        query: Annotated[SalesInsightsQuery, Query()],
    ) -> SalesInsightResponse:
        """Translate an HTTP query into a get-sales-insights use-case call."""

        use_case = _require_use_case(get_sales_insights, "GetSalesInsights")
        try:
            result = use_case.execute(question=query.question)
        except SalesPlanningError as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(error),
            ) from error
        return SalesInsightResponse(
            answer=result.answer,
            status=result.status,
            data=[
                AnalysisDatasetResponse(
                    status=dataset.status,
                    rows=[
                        AnalysisRowResponse(
                            dimensions=[
                                AnalysisCellResponse(name=cell.name, value=cell.value)
                                for cell in row.dimensions
                            ],
                            metrics=[
                                AnalysisCellResponse(name=cell.name, value=cell.value)
                                for cell in row.metrics
                            ],
                        )
                        for row in dataset.rows
                    ],
                    warnings=list(dataset.warnings),
                    metadata=[
                        AnalysisCellResponse(name=cell.name, value=cell.value)
                        for cell in dataset.metadata
                    ],
                )
                for dataset in result.data
            ],
            warnings=list(result.warnings),
        )

    @router.get(
        "/top-products",
        response_model=TopProductsResponse,
        responses={
            status.HTTP_503_SERVICE_UNAVAILABLE: {
                "model": ErrorResponse,
                "description": "Caso de uso ainda nao conectado ao adapter HTTP.",
            }
        },
        summary="Lista os cinco produtos mais vendidos no mes mais recente com vendas",
        tags=["sales"],
    )
    def top_products() -> TopProductsResponse:
        """Translate an HTTP request into a get-top-products use-case call."""

        use_case = _require_use_case(get_top_products, "GetTopProducts")
        result = use_case.execute()
        reference_month = (
            None
            if result.reference_month is None
            else SalesMonthResponse(
                year=result.reference_month.year,
                month=result.reference_month.month,
            )
        )
        return TopProductsResponse(
            reference_month=reference_month,
            products=[
                TopProductResponse(
                    product_id=product.product_id,
                    sku=product.sku,
                    name=product.name,
                    quantity_sold=product.quantity_sold,
                )
                for product in result.products
            ],
        )

    return router


def create_app(
    *,
    get_sales_insights: GetSalesInsights | None = None,
    get_top_products: GetTopProducts | None = None,
    lifespan: Lifespan[FastAPI] | None = None,
) -> FastAPI:
    """Build the HTTP adapter with replaceable use-case implementations."""

    application = FastAPI(
        title="Garage AI Sales Insights API",
        version="0.1.0",
        description="Adapter HTTP para consultas e insights de vendas.",
        lifespan=lifespan,
    )
    application.include_router(_create_router(get_sales_insights, get_top_products))
    return application


app = create_app()


def run() -> None:
    """Run the unconfigured HTTP adapter for local integration checks."""

    uvicorn.run("garage_sales.adapters.http.api:app", host="127.0.0.1", port=8000)
