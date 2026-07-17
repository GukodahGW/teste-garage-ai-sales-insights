from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from garage_sales.infrastructure.sqlalchemy import (
    CustomerModel,
    ProductModel,
    SaleModel,
    SqlAlchemyRelationalPersistence,
)


@pytest.fixture
def relational_persistence() -> Iterator[SqlAlchemyRelationalPersistence]:
    adapter = SqlAlchemyRelationalPersistence("sqlite+pysqlite:///:memory:")
    adapter.create_schema()

    with adapter.session_factory.begin() as session:
        session.add_all(
            [
                CustomerModel(id=1, name="Ana Lima", email="ana@example.com"),
                CustomerModel(id=2, name="Bruno Reis", email="bruno@example.com"),
                ProductModel(
                    id=1,
                    sku="FUR-001",
                    name="Furadeira",
                    unit_price=Decimal("399.90"),
                    active=True,
                ),
                ProductModel(
                    id=2,
                    sku="LIX-002",
                    name="Lixadeira antiga",
                    unit_price=Decimal("150.00"),
                    active=False,
                ),
                SaleModel(
                    id=100,
                    product_id=1,
                    customer_id=1,
                    quantity=2,
                    total_amount=Decimal("120.00"),
                    sold_at=datetime(2026, 1, 10, 12, tzinfo=UTC),
                ),
                SaleModel(
                    id=101,
                    product_id=2,
                    customer_id=1,
                    quantity=1,
                    total_amount=Decimal("80.00"),
                    sold_at=datetime(2026, 2, 10, 12, tzinfo=UTC),
                ),
                SaleModel(
                    id=102,
                    product_id=1,
                    customer_id=2,
                    quantity=3,
                    total_amount=Decimal("300.00"),
                    sold_at=datetime(2026, 3, 10, 12, tzinfo=UTC),
                ),
            ]
        )

    yield adapter
    adapter.dispose()
