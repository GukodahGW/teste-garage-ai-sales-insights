from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import cast

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from sqlalchemy import func, select

from garage_sales.adapters.langchain import LangChainSalesQueryPlanner
from garage_sales.application import (
    AggregateSales,
    AnalysisRow,
    AnalysisStatus,
    AnomalyAnalysis,
    BasketAnalysis,
    CohortAnalysis,
    CompareSales,
    ComparisonKind,
    FilterOperator,
    ForecastSales,
    SalesDimension,
    SalesFilter,
    SalesFilterField,
    SalesMetric,
    SortSpec,
    TimeGrain,
    TimePeriod,
    WindowKind,
    WindowSpec,
)
from garage_sales.infrastructure.sqlalchemy import (
    CustomerModel,
    OrderItemModel,
    OrderModel,
    ProductModel,
    RefundModel,
    SqlAlchemyRelationalPersistence,
)
from garage_sales.infrastructure.sqlalchemy.migrations import upgrade_database


@pytest.fixture
def analytical_persistence() -> Iterator[SqlAlchemyRelationalPersistence]:
    persistence = SqlAlchemyRelationalPersistence("sqlite+pysqlite:///:memory:")
    persistence.create_schema()
    with persistence.session_factory.begin() as session:
        session.add_all(
            [
                CustomerModel(id=1, name="Ana", email="ana@analytics.test"),
                CustomerModel(id=2, name="Bruno", email="bruno@analytics.test"),
                ProductModel(id=1, sku="MAR", name="Martelo", category="Ferramentas"),
                ProductModel(id=2, sku="FUR", name="Furadeira", category="Ferramentas"),
                ProductModel(id=3, sku="LUV", name="Luvas", category="Acessorios"),
                OrderModel(
                    id=1,
                    customer_id=1,
                    ordered_at=datetime(2026, 1, 5, tzinfo=UTC),
                    status="completed",
                    currency="BRL",
                    gross_amount=Decimal("100.00"),
                    discount_amount=Decimal("0.00"),
                    net_amount=Decimal("100.00"),
                ),
                OrderModel(
                    id=2,
                    customer_id=1,
                    ordered_at=datetime(2026, 1, 20, tzinfo=UTC),
                    status="completed",
                    currency="BRL",
                    gross_amount=Decimal("80.00"),
                    discount_amount=Decimal("0.00"),
                    net_amount=Decimal("80.00"),
                ),
                OrderModel(
                    id=3,
                    customer_id=2,
                    ordered_at=datetime(2026, 2, 10, tzinfo=UTC),
                    status="completed",
                    currency="BRL",
                    gross_amount=Decimal("150.00"),
                    discount_amount=Decimal("0.00"),
                    net_amount=Decimal("150.00"),
                ),
                OrderModel(
                    id=4,
                    customer_id=1,
                    ordered_at=datetime(2026, 2, 15, tzinfo=UTC),
                    status="completed",
                    currency="BRL",
                    gross_amount=Decimal("100.00"),
                    discount_amount=Decimal("0.00"),
                    net_amount=Decimal("100.00"),
                ),
                OrderModel(
                    id=5,
                    customer_id=2,
                    ordered_at=datetime(2026, 3, 5, tzinfo=UTC),
                    status="completed",
                    currency="BRL",
                    gross_amount=Decimal("120.00"),
                    discount_amount=Decimal("0.00"),
                    net_amount=Decimal("120.00"),
                ),
            ]
        )
        session.add_all(
            [
                _item(1, 1, 1, 2, "30.00", "60.00", "Martelo", "Ferramentas"),
                _item(2, 1, 3, 2, "20.00", "40.00", "Luvas", "Acessorios"),
                _item(3, 2, 2, 1, "80.00", "80.00", "Furadeira", "Ferramentas"),
                _item(4, 3, 1, 1, "50.00", "50.00", "Martelo", "Ferramentas"),
                _item(5, 3, 2, 1, "100.00", "100.00", "Furadeira", "Ferramentas"),
                _item(6, 4, 1, 2, "50.00", "100.00", "Martelo", "Ferramentas"),
                _item(7, 5, 2, 1, "120.00", "120.00", "Furadeira", "Ferramentas"),
                RefundModel(
                    id=1,
                    order_id=4,
                    order_item_id=6,
                    amount=Decimal("10.00"),
                    refunded_at=datetime(2026, 2, 20, tzinfo=UTC),
                ),
            ]
        )
    yield persistence
    persistence.dispose()


def _item(
    item_id: int,
    order_id: int,
    product_id: int,
    quantity: int,
    unit_price: str,
    net_amount: str,
    product_name: str,
    category_name: str,
) -> OrderItemModel:
    return OrderItemModel(
        id=item_id,
        order_id=order_id,
        product_id=product_id,
        quantity=quantity,
        unit_price=Decimal(unit_price),
        discount_amount=Decimal("0.00"),
        net_amount=Decimal(net_amount),
        product_name=product_name,
        category_name=category_name,
    )


def _metrics(row: AnalysisRow) -> dict[str, object]:
    return {cell.name: cell.value for cell in row.metrics}


def _dimensions(row: AnalysisRow) -> dict[str, object]:
    return {cell.name: cell.value for cell in row.dimensions}


def test_aggregate_uses_correct_order_and_item_grains(
    analytical_persistence: SqlAlchemyRelationalPersistence,
) -> None:
    with analytical_persistence.read() as repositories:
        total = repositories.analytics.execute(
            AggregateSales(
                metrics=(
                    SalesMetric.REVENUE,
                    SalesMetric.NET_REVENUE,
                    SalesMetric.ORDER_COUNT,
                    SalesMetric.AVERAGE_TICKET,
                )
            )
        )
        categories = repositories.analytics.execute(
            AggregateSales(
                metrics=(SalesMetric.REVENUE, SalesMetric.ORDER_COUNT),
                dimensions=(SalesDimension.CATEGORY,),
                sort=(SortSpec(SalesMetric.REVENUE),),
            )
        )

    assert _metrics(total.rows[0]) == {
        "revenue": Decimal("550.00"),
        "net_revenue": Decimal("540.00"),
        "order_count": 5,
        "average_ticket": Decimal("110.00"),
    }
    by_category = {_dimensions(row)["category"]: _metrics(row) for row in categories.rows}
    assert by_category == {
        "Acessorios": {"revenue": Decimal("40.00"), "order_count": 1},
        "Ferramentas": {"revenue": Decimal("510.00"), "order_count": 5},
    }
    assert sum(
        (cast(Decimal, values["revenue"]) for values in by_category.values()),
        Decimal("0"),
    ) == Decimal("550.00")


def test_compare_ranking_share_and_top_n_per_category_are_deterministic(
    analytical_persistence: SqlAlchemyRelationalPersistence,
) -> None:
    january = TimePeriod(
        datetime(2026, 1, 1, tzinfo=UTC),
        datetime(2026, 2, 1, tzinfo=UTC),
    )
    february = TimePeriod(
        datetime(2026, 2, 1, tzinfo=UTC),
        datetime(2026, 3, 1, tzinfo=UTC),
    )
    with analytical_persistence.read() as repositories:
        comparison = repositories.analytics.execute(
            CompareSales(
                metrics=(SalesMetric.REVENUE,),
                dimensions=(SalesDimension.CATEGORY,),
                current_period=february,
                baseline_period=january,
                sort=(
                    SortSpec(
                        SalesMetric.REVENUE,
                        comparison=ComparisonKind.PERCENTAGE_CHANGE,
                    ),
                ),
            )
        )
        ranked = repositories.analytics.execute(
            AggregateSales(
                metrics=(SalesMetric.REVENUE,),
                dimensions=(SalesDimension.CATEGORY, SalesDimension.PRODUCT),
                windows=(
                    WindowSpec(
                        WindowKind.SHARE_OF_TOTAL,
                        SalesMetric.REVENUE,
                        partition_by=(SalesDimension.CATEGORY,),
                    ),
                    WindowSpec(
                        WindowKind.RANK,
                        SalesMetric.REVENUE,
                        partition_by=(SalesDimension.CATEGORY,),
                        top_n=1,
                    ),
                ),
            )
        )

    tool_comparison = next(
        row for row in comparison.rows if _dimensions(row)["category"] == "Ferramentas"
    )
    assert _metrics(tool_comparison) == {
        "revenue.current": Decimal("250.00"),
        "revenue.baseline": Decimal("140.00"),
        "revenue.absolute_change": Decimal("110.00"),
        "revenue.percentage_change": Decimal("78.5714"),
    }
    assert {(_dimensions(row)["category"], _dimensions(row)["product"]) for row in ranked.rows} == {
        ("Acessorios", "Luvas"),
        ("Ferramentas", "Furadeira"),
    }


def test_basket_and_cohort_queries_use_order_relationships(
    analytical_persistence: SqlAlchemyRelationalPersistence,
) -> None:
    full_period = TimePeriod(
        datetime(2026, 1, 1, tzinfo=UTC),
        datetime(2026, 4, 1, tzinfo=UTC),
    )
    with analytical_persistence.read() as repositories:
        basket = repositories.analytics.execute(
            BasketAnalysis(
                period=full_period,
                minimum_orders=1,
                limit=10,
            )
        )
        cohort = repositories.analytics.execute(
            CohortAnalysis(
                acquisition_period=full_period,
                activity_period=full_period,
            )
        )

    pairs = {
        (_dimensions(row)["product_a"], _dimensions(row)["product_b"]): _metrics(row)
        for row in basket.rows
    }
    assert pairs[("Martelo", "Luvas")]["co_purchase_count"] == 1
    assert pairs[("Martelo", "Luvas")]["lift"] == Decimal("1.6667")
    january_february = next(
        row
        for row in cohort.rows
        if _dimensions(row) == {"cohort": "2026-01", "activity_period": "2026-02"}
    )
    assert _metrics(january_february)["retention_rate"] == Decimal("100.0000")


def test_planner_builds_a_compound_typed_plan_for_relational_question() -> None:
    planner = LangChainSalesQueryPlanner(
        FakeListChatModel(
            responses=[
                """{
                    "calls": [
                        {
                            "operation": "sales.compare",
                            "metrics": ["revenue"],
                            "dimensions": ["category"],
                            "current_period": {
                                "start": "2026-02-01T00:00:00Z",
                                "end": "2026-03-01T00:00:00Z"
                            },
                            "baseline_period": {
                                "start": "2026-01-01T00:00:00Z",
                                "end": "2026-02-01T00:00:00Z"
                            },
                            "sort": [{
                                "metric": "revenue",
                                "comparison": "percentage_change"
                            }],
                            "limit": 1
                        },
                        {
                            "operation": "sales.basket",
                            "metric": "lift",
                            "minimum_orders": 2
                        }
                    ]
                }"""
            ]
        )
    )

    plan = planner.plan(
        question=("Qual categoria cresceu mais e quais produtos foram mais comprados juntos?")
    )

    assert len(plan.queries) == 2
    assert isinstance(plan.queries[0], CompareSales)
    assert isinstance(plan.queries[1], BasketAnalysis)


def test_customer_metrics_forecast_anomalies_and_ambiguity_are_explicit(
    analytical_persistence: SqlAlchemyRelationalPersistence,
) -> None:
    full_period = TimePeriod(
        datetime(2026, 1, 1, tzinfo=UTC),
        datetime(2026, 4, 1, tzinfo=UTC),
    )
    with analytical_persistence.read() as repositories:
        customer_metrics = repositories.analytics.execute(
            AggregateSales(
                metrics=(
                    SalesMetric.DISTINCT_CUSTOMERS,
                    SalesMetric.REPEAT_CUSTOMER_RATE,
                    SalesMetric.PURCHASE_FREQUENCY,
                    SalesMetric.CUSTOMER_LIFETIME_VALUE,
                ),
                period=full_period,
            )
        )
        forecast = repositories.analytics.execute(
            ForecastSales(
                metric=SalesMetric.REVENUE,
                history_period=full_period,
                grain=TimeGrain.MONTH,
                horizon=2,
            )
        )
        anomalies = repositories.analytics.execute(
            AnomalyAnalysis(
                metric=SalesMetric.REVENUE,
                period=full_period,
                grain=TimeGrain.MONTH,
                sensitivity=Decimal("1"),
            )
        )

    assert _metrics(customer_metrics.rows[0]) == {
        "distinct_customers": 2,
        "repeat_customer_rate": Decimal("100.0000"),
        "purchase_frequency": Decimal("2.5000"),
        "customer_lifetime_value": Decimal("275.00"),
    }
    assert len(forecast.rows) == 2
    assert (
        dict((cell.name, cell.value) for cell in forecast.metadata)[
            "backtest_absolute_percentage_error"
        ]
        is not None
    )
    assert anomalies.status is AnalysisStatus.ANSWERED

    with analytical_persistence.session_factory.begin() as session:
        session.add(ProductModel(id=4, sku="MAR-2", name="Martelo", category="Ferramentas"))
    with analytical_persistence.read() as repositories:
        ambiguous = repositories.analytics.execute(
            AggregateSales(
                metrics=(SalesMetric.REVENUE,),
                filters=(
                    SalesFilter(
                        SalesFilterField.PRODUCT,
                        FilterOperator.EQUALS,
                        ("Martelo",),
                    ),
                ),
            )
        )
    assert ambiguous.status is AnalysisStatus.AMBIGUOUS


def test_migration_backfills_legacy_sales_without_changing_the_financial_total(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite+pysqlite:///{(tmp_path / 'analytics.db').as_posix()}"
    upgrade_database(database_url)
    persistence = SqlAlchemyRelationalPersistence(database_url)
    try:
        with persistence.session_factory() as session:
            assert session.scalar(select(func.count(OrderModel.id))) == 33
            assert session.scalar(select(func.count(OrderItemModel.id))) == 33
        with persistence.read() as repositories:
            total = repositories.analytics.execute(
                AggregateSales(
                    metrics=(SalesMetric.REVENUE, SalesMetric.ORDER_COUNT),
                    period=TimePeriod(
                        datetime(2025, 1, 1, tzinfo=UTC),
                        datetime(2026, 1, 1, tzinfo=UTC),
                    ),
                )
            )
            categories = repositories.analytics.execute(
                AggregateSales(
                    metrics=(SalesMetric.REVENUE,),
                    dimensions=(SalesDimension.CATEGORY,),
                    period=TimePeriod(
                        datetime(2025, 1, 1, tzinfo=UTC),
                        datetime(2026, 1, 1, tzinfo=UTC),
                    ),
                )
            )
        assert _metrics(total.rows[0]) == {
            "revenue": Decimal("2309.78"),
            "order_count": 33,
        }
        assert sum(
            (cast(Decimal, _metrics(row)["revenue"]) for row in categories.rows),
            Decimal("0"),
        ) == Decimal("2309.78")
    finally:
        persistence.dispose()


def test_plan_components_reject_invalid_cross_field_combinations() -> None:
    with pytest.raises(ValueError, match="average_ticket"):
        AggregateSales(
            metrics=(SalesMetric.AVERAGE_TICKET,),
            dimensions=(SalesDimension.PRODUCT,),
        )

    with pytest.raises(ValueError, match="granularidade temporal"):
        AggregateSales(
            metrics=(SalesMetric.REVENUE,),
            dimensions=(SalesDimension.MONTH, SalesDimension.YEAR),
        )

    with pytest.raises(ValueError, match="partition_by"):
        AggregateSales(
            metrics=(SalesMetric.REVENUE,),
            dimensions=(SalesDimension.PRODUCT,),
            windows=(
                WindowSpec(
                    WindowKind.RANK,
                    SalesMetric.REVENUE,
                    partition_by=(SalesDimension.CATEGORY,),
                ),
            ),
        )

    with pytest.raises(ValueError, match="current_period"):
        CompareSales(
            metrics=(SalesMetric.REVENUE,),
            current_period=TimePeriod(),
            baseline_period=TimePeriod(),
        )

    with pytest.raises(ValueError, match="unico filtro"):
        AggregateSales(
            metrics=(SalesMetric.REVENUE,),
            filters=(
                SalesFilter(
                    SalesFilterField.CURRENCY,
                    FilterOperator.EQUALS,
                    ("BRL",),
                ),
                SalesFilter(
                    SalesFilterField.CURRENCY,
                    FilterOperator.NOT_EQUALS,
                    ("USD",),
                ),
            ),
        )
