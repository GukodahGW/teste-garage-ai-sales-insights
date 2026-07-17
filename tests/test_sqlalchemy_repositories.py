from decimal import Decimal

import pytest

from garage_sales.application import CustomerQueries, ProductQueries, SalesQueries
from garage_sales.domain import CustomerCriteria, ProductCriteria, SaleCriteria
from garage_sales.infrastructure.sqlalchemy import SqlAlchemyPersistence


def test_get_sale_by_id(persistence: SqlAlchemyPersistence) -> None:
    sale = SalesQueries(persistence).get_sale_by_id(100)

    assert sale is not None
    assert sale.customer_id == 1
    assert sale.total_amount == Decimal("120.00")


def test_get_sales_by_combines_backend_independent_filters(
    persistence: SqlAlchemyPersistence,
) -> None:
    sales = SalesQueries(persistence).get_sales_by(
        SaleCriteria(customer_id=1, min_total=Decimal("100.00"))
    )

    assert [sale.id for sale in sales] == [100]


def test_customer_and_product_queries(persistence: SqlAlchemyPersistence) -> None:
    customers = CustomerQueries(persistence).get_customers_by(CustomerCriteria(name_contains="ana"))
    products = ProductQueries(persistence).get_products_by(
        ProductCriteria(active=True, min_price=Decimal("300.00"))
    )

    assert [customer.id for customer in customers] == [1]
    assert [product.id for product in products] == [1]


def test_find_applies_order_and_pagination(persistence: SqlAlchemyPersistence) -> None:
    sales = SalesQueries(persistence).get_sales_by(SaleCriteria(limit=1, offset=1))

    assert [sale.id for sale in sales] == [101]


def test_invalid_criteria_fail_before_reaching_the_database() -> None:
    with pytest.raises(ValueError, match="min_total"):
        SaleCriteria(min_total=Decimal("20"), max_total=Decimal("10"))

    with pytest.raises(ValueError, match="limit"):
        ProductCriteria(limit=0)

