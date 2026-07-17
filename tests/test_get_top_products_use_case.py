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
    Customer,
    CustomerCriteria,
    CustomerReadRepository,
    Product,
    ProductCriteria,
    ProductReadRepository,
    RelationalReadUnitOfWork,
    Sale,
    SaleCriteria,
    SaleReadRepository,
)
from garage_sales.infrastructure.sqlalchemy import SqlAlchemyRelationalPersistence


class FakeSaleRepository:
    def __init__(self, sales: list[Sale]) -> None:
        self._sales = sales
        self.received_criteria: list[SaleCriteria] = []

    def get_by_id(self, sale_id: int) -> Sale | None:
        return next((sale for sale in self._sales if sale.id == sale_id), None)

    def get_latest(self) -> Sale | None:
        return max(self._sales, key=lambda sale: (sale.sold_at, sale.id), default=None)

    def find(self, criteria: SaleCriteria) -> list[Sale]:
        self.received_criteria.append(criteria)
        filtered = [
            sale
            for sale in self._sales
            if (criteria.sold_from is None or sale.sold_at >= criteria.sold_from)
            and (criteria.sold_until is None or sale.sold_at <= criteria.sold_until)
        ]
        filtered.sort(key=lambda sale: (sale.sold_at, sale.id), reverse=True)
        return filtered[criteria.offset : criteria.offset + criteria.limit]


class EmptyCustomerRepository:
    def get_by_id(self, customer_id: int) -> Customer | None:
        return None

    def find(self, criteria: CustomerCriteria) -> list[Customer]:
        return []


class FakeProductRepository:
    def __init__(self, products: list[Product]) -> None:
        self._products = {product.id: product for product in products}

    def get_by_id(self, product_id: int) -> Product | None:
        return self._products.get(product_id)

    def find(self, criteria: ProductCriteria) -> list[Product]:
        products = list(self._products.values())
        return products[criteria.offset : criteria.offset + criteria.limit]


class FakeReadUnitOfWork:
    sales: SaleReadRepository
    customers: CustomerReadRepository
    products: ProductReadRepository

    def __init__(self, sales: list[Sale], products: list[Product]) -> None:
        self.sale_repository = FakeSaleRepository(sales)
        self.sales = self.sale_repository
        self.customers = EmptyCustomerRepository()
        self.products = FakeProductRepository(products)

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


def _product(product_id: int) -> Product:
    return Product(
        id=product_id,
        sku=f"PROD-{product_id:03d}",
        name=f"Produto {product_id}",
        unit_price=Decimal("10.00"),
        active=True,
    )


def _sale(
    sale_id: int,
    *,
    product_id: int | None,
    quantity: int,
    sold_at: datetime,
) -> Sale:
    return Sale(
        id=sale_id,
        customer_id=None,
        product_id=product_id,
        quantity=quantity,
        total_amount=Decimal("10.00") * quantity,
        sold_at=sold_at,
    )


def test_returns_only_the_five_best_selling_products_from_latest_month_with_sales() -> None:
    products = [_product(product_id) for product_id in range(1, 8)]
    march_sales = [
        _sale(
            product_id,
            product_id=product_id,
            quantity=product_id,
            sold_at=datetime(2026, 3, product_id, 12, tzinfo=UTC),
        )
        for product_id in range(1, 8)
    ]
    sales = [
        *march_sales,
        _sale(
            101,
            product_id=1,
            quantity=20,
            sold_at=datetime(2026, 3, 31, 23, 59, 59, 999999, tzinfo=UTC),
        ),
        _sale(
            102,
            product_id=7,
            quantity=100,
            sold_at=datetime(2026, 2, 28, 23, 59, 59, tzinfo=UTC),
        ),
    ]
    unit_of_work = FakeReadUnitOfWork(sales, products)
    use_case = GetTopProductsUseCase(
        relational_persistence=FakeRelationalPersistence(unit_of_work),
    )

    result = use_case.execute()

    assert result == TopProductsResult(
        reference_month=SalesMonth(year=2026, month=3),
        products=(
            TopProduct(product_id=1, sku="PROD-001", name="Produto 1", quantity_sold=21),
            TopProduct(product_id=7, sku="PROD-007", name="Produto 7", quantity_sold=7),
            TopProduct(product_id=6, sku="PROD-006", name="Produto 6", quantity_sold=6),
            TopProduct(product_id=5, sku="PROD-005", name="Produto 5", quantity_sold=5),
            TopProduct(product_id=4, sku="PROD-004", name="Produto 4", quantity_sold=4),
        ),
    )
    assert unit_of_work.sale_repository.received_criteria == [
        SaleCriteria(
            sold_from=datetime(2026, 3, 1, tzinfo=UTC),
            sold_until=datetime(2026, 3, 31, 23, 59, 59, 999999, tzinfo=UTC),
            limit=500,
        )
    ]


def test_paginates_all_sales_before_ranking() -> None:
    product = _product(1)
    sales = [
        _sale(
            sale_id,
            product_id=product.id,
            quantity=1,
            sold_at=datetime(2026, 3, 15, 12, tzinfo=UTC),
        )
        for sale_id in range(1, 502)
    ]
    unit_of_work = FakeReadUnitOfWork(sales, [product])
    use_case = GetTopProductsUseCase(
        relational_persistence=FakeRelationalPersistence(unit_of_work),
    )

    assert use_case.execute() == TopProductsResult(
        reference_month=SalesMonth(year=2026, month=3),
        products=(
            TopProduct(
                product_id=1,
                sku="PROD-001",
                name="Produto 1",
                quantity_sold=501,
            ),
        ),
    )
    assert [criteria.offset for criteria in unit_of_work.sale_repository.received_criteria] == [
        0,
        500,
    ]


def test_returns_an_empty_list_when_there_are_no_sales() -> None:
    unit_of_work = FakeReadUnitOfWork([], [])
    use_case = GetTopProductsUseCase(
        relational_persistence=FakeRelationalPersistence(unit_of_work),
    )

    assert use_case.execute() == TopProductsResult(reference_month=None, products=())
    assert unit_of_work.sale_repository.received_criteria == []


def test_uses_the_active_sqlalchemy_repositories(
    relational_persistence: SqlAlchemyRelationalPersistence,
) -> None:
    use_case = GetTopProductsUseCase(
        relational_persistence=relational_persistence,
    )

    assert use_case.execute() == TopProductsResult(
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
