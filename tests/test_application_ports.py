from garage_sales.application import (
    GetSalesInsights,
    GetTopProducts,
    SalesInsight,
    SalesMonth,
    TopProduct,
    TopProductsResult,
)


class StubSalesInsights:
    def execute(self, *, question: str, cursor: str | None = None) -> SalesInsight:
        del cursor
        return SalesInsight(answer=f"Resposta para: {question}")


class StubTopProducts:
    def execute(self) -> TopProductsResult:
        return TopProductsResult(
            reference_month=SalesMonth(year=2026, month=3),
            products=(
                TopProduct(
                    product_id=7,
                    sku="PROD-007",
                    name="Produto 7",
                    quantity_sold=42,
                ),
            ),
        )


def _ask_from_any_inbound_adapter(port: GetSalesInsights, question: str) -> str:
    return port.execute(question=question).answer


def _top_products_from_any_inbound_adapter(port: GetTopProducts) -> TopProductsResult:
    return port.execute()


def test_sales_insights_use_case_is_exposed_through_an_inbound_port() -> None:
    answer = _ask_from_any_inbound_adapter(
        StubSalesInsights(),
        "Qual foi o produto mais vendido na ultima semana?",
    )

    assert answer == "Resposta para: Qual foi o produto mais vendido na ultima semana?"


def test_top_products_use_case_is_exposed_through_an_inbound_port() -> None:
    products = _top_products_from_any_inbound_adapter(StubTopProducts())

    assert products == TopProductsResult(
        reference_month=SalesMonth(year=2026, month=3),
        products=(
            TopProduct(
                product_id=7,
                sku="PROD-007",
                name="Produto 7",
                quantity_sold=42,
            ),
        ),
    )
