from fastapi.testclient import TestClient

from garage_sales.adapters.http import create_app
from garage_sales.application import (
    AggregateSales,
    SalesInsight,
    SalesMetric,
    SalesMonth,
    SalesPlanningError,
    SalesQueryPlan,
    TopProduct,
    TopProductsResult,
)


class StubGetSalesInsights:
    def __init__(self) -> None:
        self.received_question: str | None = None

    def execute(self, *, question: str, cursor: str | None = None) -> SalesInsight:
        del cursor
        self.received_question = question
        return SalesInsight(answer="A furadeira foi o produto mais vendido.")


class StubPagedSalesInsights:
    def __init__(self) -> None:
        self.received_cursor: str | None = None

    def execute(self, *, question: str, cursor: str | None = None) -> SalesInsight:
        del question
        self.received_cursor = cursor
        return SalesInsight(answer="Pagina seguinte.", next_cursor="next-page")


class StubDiagnosticSalesInsights:
    def execute(self, *, question: str, cursor: str | None = None) -> SalesInsight:
        del question, cursor
        plan = SalesQueryPlan(
            queries=(AggregateSales(metrics=(SalesMetric.REVENUE,)),)
        )
        return SalesInsight(answer="Receita calculada.", plan=plan)


class StubGetTopProducts:
    def execute(self) -> TopProductsResult:
        return TopProductsResult(
            reference_month=SalesMonth(year=2026, month=3),
            products=tuple(
                TopProduct(
                    product_id=index,
                    sku=f"PROD-{index:03d}",
                    name=f"Produto {index}",
                    quantity_sold=100 - index,
                )
                for index in range(1, 6)
            ),
        )


class StubGetTopProductsWithoutSales:
    def execute(self) -> TopProductsResult:
        return TopProductsResult(reference_month=None, products=())


class StubInvalidSalesPlan:
    def execute(self, *, question: str, cursor: str | None = None) -> SalesInsight:
        del question, cursor
        raise SalesPlanningError("nao foi possivel produzir um plano valido")


def test_sales_insights_endpoint_normalizes_input_and_serializes_output() -> None:
    use_case = StubGetSalesInsights()
    client = TestClient(create_app(get_sales_insights=use_case))

    response = client.get(
        "/sales-insights",
        params={"question": "  Qual foi o produto mais vendido na última semana?  "},
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.json() == {"answer": "A furadeira foi o produto mais vendido."}
    assert use_case.received_question == "Qual foi o produto mais vendido na última semana?"


def test_sales_insights_endpoint_propagates_comparison_cursors() -> None:
    use_case = StubPagedSalesInsights()
    client = TestClient(create_app(get_sales_insights=use_case))

    response = client.get(
        "/sales-insights",
        params={"question": "Compare as categorias", "cursor": "current-page"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "answer": "Pagina seguinte.",
        "next_cursor": "next-page",
    }
    assert use_case.received_cursor == "current-page"


def test_sales_insights_endpoint_exposes_the_typed_plan_only_when_requested() -> None:
    client = TestClient(create_app(get_sales_insights=StubDiagnosticSalesInsights()))

    regular = client.get("/sales-insights", params={"question": "Quanto vendemos?"})
    diagnostic = client.get(
        "/sales-insights",
        params={"question": "Quanto vendemos?", "include_plan": "true"},
    )

    assert regular.json() == {"answer": "Receita calculada."}
    assert diagnostic.status_code == 200
    assert diagnostic.json()["plan"]["queries"][0] == {
        "metrics": ["revenue"],
        "dimensions": [],
        "filters": [],
        "period": {"start": None, "end": None},
        "sort": [],
        "limit": None,
    }


def test_sales_insights_endpoint_rejects_missing_blank_or_unknown_input() -> None:
    client = TestClient(create_app(get_sales_insights=StubGetSalesInsights()))

    assert client.get("/sales-insights").status_code == 422
    assert client.get("/sales-insights", params={"question": "   "}).status_code == 422
    assert (
        client.get(
            "/sales-insights",
            params={"question": "Quanto vendemos?", "unexpected": "value"},
        ).status_code
        == 422
    )


def test_sales_insights_endpoint_limits_question_size() -> None:
    client = TestClient(create_app(get_sales_insights=StubGetSalesInsights()))

    response = client.get("/sales-insights", params={"question": "a" * 2_001})

    assert response.status_code == 422


def test_sales_insights_endpoint_reports_invalid_plans_without_internal_error() -> None:
    client = TestClient(create_app(get_sales_insights=StubInvalidSalesPlan()))

    response = client.get("/sales-insights", params={"question": "Pergunta ambigua"})

    assert response.status_code == 422
    assert response.json() == {"detail": "nao foi possivel produzir um plano valido"}


def test_top_products_endpoint_returns_the_use_case_output() -> None:
    client = TestClient(create_app(get_top_products=StubGetTopProducts()))

    response = client.get("/top-products")

    assert response.status_code == 200
    assert response.json() == {
        "reference_month": {"year": 2026, "month": 3},
        "products": [
            {
                "product_id": index,
                "sku": f"PROD-{index:03d}",
                "name": f"Produto {index}",
                "quantity_sold": 100 - index,
            }
            for index in range(1, 6)
        ],
    }


def test_top_products_endpoint_has_no_reference_month_without_sales() -> None:
    client = TestClient(create_app(get_top_products=StubGetTopProductsWithoutSales()))

    response = client.get("/top-products")

    assert response.status_code == 200
    assert response.json() == {"reference_month": None, "products": []}


def test_unconfigured_http_adapter_reports_service_unavailable() -> None:
    client = TestClient(create_app())

    sales_response = client.get("/sales-insights", params={"question": "Quanto vendemos?"})
    top_products_response = client.get("/top-products")

    assert sales_response.status_code == 503
    assert sales_response.json() == {
        "detail": "O caso de uso GetSalesInsights ainda nao foi configurado."
    }
    assert top_products_response.status_code == 503
    assert top_products_response.json() == {
        "detail": "O caso de uso GetTopProducts ainda nao foi configurado."
    }


def test_openapi_and_browser_documentation_are_available() -> None:
    client = TestClient(create_app())

    assert client.get("/openapi.json").status_code == 200
    assert client.get("/docs").status_code == 200
