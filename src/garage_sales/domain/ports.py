from types import TracebackType
from typing import Protocol, Self

from garage_sales.domain.analytics import AnalysisDataset, SalesAnalysisQuery
from garage_sales.domain.criteria import CustomerCriteria, ProductCriteria, SaleCriteria
from garage_sales.domain.entities import Customer, Product, Sale


class SaleReadRepository(Protocol):
    def get_by_id(self, sale_id: int) -> Sale | None: ...

    def get_latest(self) -> Sale | None: ...

    def find(self, criteria: SaleCriteria) -> list[Sale]: ...


class CustomerReadRepository(Protocol):
    def get_by_id(self, customer_id: int) -> Customer | None: ...

    def find(self, criteria: CustomerCriteria) -> list[Customer]: ...


class ProductReadRepository(Protocol):
    def get_by_id(self, product_id: int) -> Product | None: ...

    def find(self, criteria: ProductCriteria) -> list[Product]: ...


class SalesAnalyticsRepository(Protocol):
    """Execute only validated semantic queries; never arbitrary SQL."""

    def execute(self, query: SalesAnalysisQuery) -> AnalysisDataset: ...


class RelationalReadUnitOfWork(Protocol):
    sales: SaleReadRepository
    customers: CustomerReadRepository
    products: ProductReadRepository

    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...


class RelationalAnalyticsReadUnitOfWork(RelationalReadUnitOfWork, Protocol):
    analytics: SalesAnalyticsRepository


class RelationalPersistence(Protocol):
    """Porta para consultas em um banco de dados relacional."""

    def read(self) -> RelationalReadUnitOfWork: ...
