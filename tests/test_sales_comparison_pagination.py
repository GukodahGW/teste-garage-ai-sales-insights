from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import event

from garage_sales.application import (
    CompareSales,
    ComparisonKind,
    RepositorySalesQueryExecutor,
    SalesDimension,
    SalesMetric,
    SalesQueryPlan,
    SortDirection,
    SortSpec,
    TimePeriod,
)
from garage_sales.domain import SalesAnalysisCursorError
from garage_sales.infrastructure.sqlalchemy import (
    ProductModel,
    SaleModel,
    SqlAlchemyRelationalPersistence,
)


def _month(year: int, month: int) -> TimePeriod:
    if month == 12:
        following = datetime(year + 1, 1, 1, tzinfo=UTC)
    else:
        following = datetime(year, month + 1, 1, tzinfo=UTC)
    return TimePeriod(
        start=datetime(year, month, 1, tzinfo=UTC),
        end=following.replace(microsecond=0) - _MICROSECOND,
    )


_MICROSECOND = timedelta(microseconds=1)


def _comparison_query(*, direction: SortDirection = SortDirection.DESCENDING) -> CompareSales:
    return CompareSales(
        metrics=(SalesMetric.REVENUE,),
        dimensions=(SalesDimension.CATEGORY,),
        current_period=_month(2024, 2),
        baseline_period=_month(2024, 1),
        sort=(
            SortSpec(
                SalesMetric.REVENUE,
                direction=direction,
                comparison=ComparisonKind.PERCENTAGE_CHANGE,
            ),
        ),
    )


def _seed_comparison_groups(
    persistence: SqlAlchemyRelationalPersistence,
    *,
    count: int,
) -> None:
    with persistence.session_factory.begin() as session:
        for index in range(count):
            product_id = 1_000 + index
            session.add(
                ProductModel(
                    id=product_id,
                    sku=f"PAGE-{index:03d}",
                    name=f"Paged product {index:03d}",
                    category=f"Category {index:03d}",
                    unit_price=Decimal("10.00"),
                    active=True,
                )
            )
            session.add_all(
                (
                    SaleModel(
                        id=10_000 + index,
                        product_id=product_id,
                        quantity=1,
                        total_amount=Decimal("10.00"),
                        sold_at=datetime(2024, 1, 15, tzinfo=UTC),
                    ),
                    SaleModel(
                        id=20_000 + index,
                        product_id=product_id,
                        quantity=1,
                        total_amount=Decimal(10 + index),
                        sold_at=datetime(2024, 2, 15, tzinfo=UTC),
                    ),
                )
            )


def test_compare_uses_one_database_statement(
    relational_persistence: SqlAlchemyRelationalPersistence,
) -> None:
    statements: list[str] = []

    def capture_statement(*args: object) -> None:
        statement = str(args[2])
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(
        relational_persistence.engine,
        "before_cursor_execute",
        capture_statement,
    )
    try:
        RepositorySalesQueryExecutor(relational_persistence).execute(
            plan=SalesQueryPlan(queries=(_comparison_query(),))
        )
    finally:
        event.remove(
            relational_persistence.engine,
            "before_cursor_execute",
            capture_statement,
        )

    assert len(statements) == 1
    assert "CASE WHEN" in statements[0]


def test_compare_preserves_groups_present_in_only_one_period(
    relational_persistence: SqlAlchemyRelationalPersistence,
) -> None:
    query = CompareSales(
        metrics=(
            SalesMetric.REVENUE,
            SalesMetric.SALE_COUNT,
            SalesMetric.UNITS_SOLD,
            SalesMetric.AVERAGE_TICKET,
        ),
        dimensions=(SalesDimension.CATEGORY,),
        current_period=_month(2026, 3),
        baseline_period=_month(2026, 2),
        sort=(
            SortSpec(
                SalesMetric.REVENUE,
                comparison=ComparisonKind.PERCENTAGE_CHANGE,
            ),
        ),
    )

    with relational_persistence.read() as repositories:
        result = repositories.analytics.compare(query)

    assert [row.dimension_key() for row in result.rows] == [
        ("Acabamento",),
        ("Ferramentas",),
    ]
    acabamento, ferramentas = result.rows
    assert acabamento.metric_value("revenue.current") == Decimal("0.00")
    assert acabamento.metric_value("revenue.baseline") == Decimal("80.00")
    assert acabamento.metric_value("revenue.percentage_change") == Decimal("-100.0000")
    assert acabamento.metric_value("average_ticket.current") == Decimal("0.00")
    assert ferramentas.metric_value("units_sold.current") == 3
    assert ferramentas.metric_value("units_sold.baseline") == 0
    assert ferramentas.metric_value("revenue.percentage_change") is None


def test_compare_returns_no_rows_when_both_periods_are_empty(
    relational_persistence: SqlAlchemyRelationalPersistence,
) -> None:
    query = CompareSales(
        metrics=(SalesMetric.REVENUE,),
        current_period=_month(2023, 2),
        baseline_period=_month(2023, 1),
    )

    with relational_persistence.read() as repositories:
        result = repositories.analytics.compare(query)

    assert result.rows == ()
    assert result.next_cursor is None


def test_compare_pages_with_a_stable_keyset_cursor(
    relational_persistence: SqlAlchemyRelationalPersistence,
) -> None:
    _seed_comparison_groups(relational_persistence, count=105)
    query = _comparison_query()

    with relational_persistence.read() as repositories:
        first_page = repositories.analytics.compare(query)
        assert first_page.next_cursor is not None
        second_page = repositories.analytics.compare(query, cursor=first_page.next_cursor)

    assert len(first_page.rows) == 100
    assert len(second_page.rows) == 5
    assert second_page.next_cursor is None
    categories = [
        str(row.dimensions[0].value)
        for row in (*first_page.rows, *second_page.rows)
    ]
    assert categories == [f"Category {index:03d}" for index in reversed(range(105))]
    assert len(categories) == len(set(categories))


def test_compare_rejects_a_cursor_from_another_query(
    relational_persistence: SqlAlchemyRelationalPersistence,
) -> None:
    _seed_comparison_groups(relational_persistence, count=105)
    query = _comparison_query()

    with relational_persistence.read() as repositories:
        cursor = repositories.analytics.compare(query).next_cursor
        assert cursor is not None
        with pytest.raises(SalesAnalysisCursorError, match="outra consulta"):
            repositories.analytics.compare(
                _comparison_query(direction=SortDirection.ASCENDING),
                cursor=cursor,
            )


@pytest.mark.parametrize("cursor", ["not-base64!", "", "x" * 4_097])
def test_compare_rejects_malformed_cursors(
    relational_persistence: SqlAlchemyRelationalPersistence,
    cursor: str,
) -> None:
    with relational_persistence.read() as repositories:
        with pytest.raises(SalesAnalysisCursorError, match="cursor invalido"):
            repositories.analytics.compare(_comparison_query(), cursor=cursor)
