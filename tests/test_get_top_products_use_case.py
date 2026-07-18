from datetime import UTC, datetime
from decimal import Decimal
from types import TracebackType
from typing import Self

from garage_sales.application import (
    GetTopProductsUseCase,
    SalesMonth,
    TopProduct,
    TopProductsResult,
)
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
from garage_sales.infrastructure.sqlalchemy import SqlAlchemyRelationalPersistence


class FakeSaleRepository:
    def __init__(self, sales: list[Sale]) -> None:
        self._sales = sales

    def get_by_id(self, sale_id: int) -> Sale | None:
        return next((sale for sale in self._sales if sale.id == sale_id), None)

    def get_latest(self) -> Sale | None:
        return max(self._sales, key=lambda sale: (sale.sold_at, sale.id), default=None)

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


class FakeSalesAnalyticsRepository:
    def __init__(self, products: tuple[ProductSalesTotal, ...]) -> None:
        self._products = products
        self.received_top_products: list[tuple[datetime | None, datetime | None, int]] = []

    def aggregate(self, query: AggregateSales) -> SalesAnalysisResult:
        del query
        raise AssertionError("aggregate nao deveria ser chamado")

    def compare(
        self,
        query: CompareSales,
        *,
        cursor: str | None = None,
    ) -> SalesAnalysisResult:
        del query, cursor
        raise AssertionError("compare nao deveria ser chamado")

    def top_products(
        self,
        *,
        sold_from: datetime | None = None,
        sold_until: datetime | None = None,
        limit: int = 5,
    ) -> tuple[ProductSalesTotal, ...]:
        self.received_top_products.append((sold_from, sold_until, limit))
        return self._products[:limit]


class FakeReadUnitOfWork:
    sales: SaleReadRepository
    customers: CustomerReadRepository
    products: ProductReadRepository
    analytics: SalesAnalyticsRepository

    def __init__(self, sales: list[Sale], products: tuple[ProductSalesTotal, ...]) -> None:
        self.sales = FakeSaleRepository(sales)
        self.customers = EmptyCustomerRepository()
        self.products = EmptyProductRepository()
        self.fake_analytics = FakeSalesAnalyticsRepository(products)
        self.analytics = self.fake_analytics

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
    def __init__(self, unit_of_work: FakeReadUnitOfWork) -> None:
        self.unit_of_work = unit_of_work

    def read(self) -> RelationalReadUnitOfWork:
        return self.unit_of_work


def _sale(sale_id: int, sold_at: datetime) -> Sale:
    return Sale(
        id=sale_id,
        customer_id=None,
        product_id=1,
        quantity=1,
        total_amount=Decimal("10.00"),
        sold_at=sold_at,
    )


def test_uses_database_aggregation_for_latest_month_and_limits_to_five() -> None:
    products = tuple(
        ProductSalesTotal(
            product_id=product_id,
            sku=f"PROD-{product_id:03d}",
            name=f"Produto {product_id}",
            quantity_sold=100 - product_id,
        )
        for product_id in range(1, 8)
    )
    unit_of_work = FakeReadUnitOfWork(
        [_sale(1, datetime(2026, 3, 31, 12, tzinfo=UTC))],
        products,
    )

    result = GetTopProductsUseCase(
        relational_persistence=FakeRelationalPersistence(unit_of_work)
    ).execute()

    assert result == TopProductsResult(
        reference_month=SalesMonth(year=2026, month=3),
        products=tuple(
            TopProduct(
                product_id=product_id,
                sku=f"PROD-{product_id:03d}",
                name=f"Produto {product_id}",
                quantity_sold=100 - product_id,
            )
            for product_id in range(1, 6)
        ),
    )
    assert unit_of_work.fake_analytics.received_top_products == [
        (
            datetime(2026, 3, 1, tzinfo=UTC),
            datetime(2026, 3, 31, 23, 59, 59, 999999, tzinfo=UTC),
            5,
        )
    ]


def test_returns_an_empty_list_when_there_are_no_sales() -> None:
    unit_of_work = FakeReadUnitOfWork([], ())

    result = GetTopProductsUseCase(
        relational_persistence=FakeRelationalPersistence(unit_of_work)
    ).execute()

    assert result == TopProductsResult(reference_month=None, products=())
    assert unit_of_work.fake_analytics.received_top_products == []


def test_uses_the_active_sqlalchemy_aggregation_repository(
    relational_persistence: SqlAlchemyRelationalPersistence,
) -> None:
    result = GetTopProductsUseCase(relational_persistence=relational_persistence).execute()

    assert result == TopProductsResult(
        reference_month=SalesMonth(year=2026, month=3),
        products=(
            TopProduct(
                product_id=1,
                sku="FUR-001",
                name="Furadeira",
                quantity_sold=3,
            ),
        ),
    )
