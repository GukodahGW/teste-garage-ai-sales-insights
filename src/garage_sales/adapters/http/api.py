from typing import Annotated, TypeVar

from fastapi import APIRouter, FastAPI, HTTPException, Query, status
from fastapi.encoders import jsonable_encoder
from starlette.types import Lifespan

from garage_sales.adapters.http.schemas import (
    ErrorResponse,
    SalesInsightResponse,
    SalesInsightsQuery,
    SalesMonthResponse,
    TopProductResponse,
    TopProductsResponse,
)
from garage_sales.application import GetSalesInsights, GetTopProducts, SalesPlanningError
from garage_sales.domain import SalesAnalysisCursorError

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
                "description": "A pergunta ou o cursor nao produziu uma consulta segura.",
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
            result = use_case.execute(question=query.question, cursor=query.cursor)
        except (SalesAnalysisCursorError, SalesPlanningError) as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(error),
            ) from error
        return SalesInsightResponse(
            answer=result.answer,
            next_cursor=result.next_cursor,
            plan=(
                jsonable_encoder(result.plan)
                if query.include_plan and result.plan is not None
                else None
            ),
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
