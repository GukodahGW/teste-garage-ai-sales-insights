from datetime import datetime
from types import TracebackType
from typing import Self

from garage_sales.application import SalesQueries
from garage_sales.domain import (
    AggregateSales,
    CompareSales,
    Customer,
    CustomerCriteria,
    CustomerReadRepository,
    Product,
    ProductCriteria,
    ProductReadRepository,
    ProductSalesTotal,
    RelationalReadUnitOfWork,
    Sale,
    SaleCriteria,
    SaleReadRepository,
    SalesAnalysisResult,
    SalesAnalyticsRepository,
)


class FakeSaleRepository:
    def __init__(self, sales: list[Sale]) -> None:
        self._sales = sales

    def get_by_id(self, sale_id: int) -> Sale | None:
        return next((sale for sale in self._sales if sale.id == sale_id), None)

    def get_latest(self) -> Sale | None:
        return self._sales[-1] if self._sales else None

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


class UnexpectedAnalyticsRepository:
    def aggregate(self, query: AggregateSales) -> SalesAnalysisResult:
        del query
        raise AssertionError("analytics nao deveria ser chamado")

    def compare(
        self,
        query: CompareSales,
        *,
        cursor: str | None = None,
    ) -> SalesAnalysisResult:
        del query, cursor
        raise AssertionError("analytics nao deveria ser chamado")

    def top_products(
        self,
        *,
        sold_from: datetime | None = None,
        sold_until: datetime | None = None,
        limit: int = 5,
    ) -> tuple[ProductSalesTotal, ...]:
        raise AssertionError("analytics nao deveria ser chamado")


class FakeRelationalReadUnitOfWork:
    sales: SaleReadRepository
    customers: CustomerReadRepository
    products: ProductReadRepository
    analytics: SalesAnalyticsRepository

    def __init__(self, sales: list[Sale]) -> None:
        self.sales = FakeSaleRepository(sales)
        self.customers = EmptyCustomerRepository()
        self.products = EmptyProductRepository()
        self.analytics = UnexpectedAnalyticsRepository()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None


class FakeRelationalPersistence:
    def __init__(self, sales: list[Sale]) -> None:
        self._sales = sales

    def read(self) -> RelationalReadUnitOfWork:
        return FakeRelationalReadUnitOfWork(self._sales)


def test_query_service_accepts_another_relational_implementation() -> None:
    from datetime import UTC, datetime
    from decimal import Decimal

    expected = Sale(
        id=7,
        customer_id=3,
        total_amount=Decimal("42.00"),
        sold_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    queries = SalesQueries(FakeRelationalPersistence([expected]))

    assert queries.get_sale_by_id(7) == expected
