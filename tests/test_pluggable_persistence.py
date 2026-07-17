from types import TracebackType
from typing import Self

from garage_sales.application import SalesQueries
from garage_sales.domain import (
    Customer,
    CustomerCriteria,
    CustomerReadRepository,
    Product,
    ProductCriteria,
    ProductReadRepository,
    Sale,
    SaleCriteria,
    SaleReadRepository,
)


class FakeSaleRepository:
    def __init__(self, sales: list[Sale]) -> None:
        self._sales = sales

    def get_by_id(self, sale_id: int) -> Sale | None:
        return next((sale for sale in self._sales if sale.id == sale_id), None)

    def find(self, criteria: SaleCriteria) -> list[Sale]:
        return self._sales[criteria.offset : criteria.offset + criteria.limit]


class EmptyCustomerRepository:
    def get_by_id(self, customer_id: int) -> Customer | None:
        return None

    def find(self, criteria: CustomerCriteria) -> list[Customer]:
        return []


class EmptyProductRepository:
    def get_by_id(self, product_id: int) -> Product | None:
        return None

    def find(self, criteria: ProductCriteria) -> list[Product]:
        return []


class FakeReadUnitOfWork:
    sales: SaleReadRepository
    customers: CustomerReadRepository
    products: ProductReadRepository

    def __init__(self, sales: list[Sale]) -> None:
        self.sales = FakeSaleRepository(sales)
        self.customers = EmptyCustomerRepository()
        self.products = EmptyProductRepository()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None


class FakePersistence:
    def __init__(self, sales: list[Sale]) -> None:
        self._sales = sales

    def read(self) -> FakeReadUnitOfWork:
        return FakeReadUnitOfWork(self._sales)


def test_query_service_accepts_another_persistence_implementation() -> None:
    from datetime import UTC, datetime
    from decimal import Decimal

    expected = Sale(
        id=7,
        customer_id=3,
        total_amount=Decimal("42.00"),
        sold_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    queries = SalesQueries(FakePersistence([expected]))

    assert queries.get_sale_by_id(7) == expected
