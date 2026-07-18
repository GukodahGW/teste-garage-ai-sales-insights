from __future__ import annotations

from dataclasses import dataclass

from garage_sales.domain.analytics import (
    AggregateSales,
    CompareSales,
    ProductSalesTotal,
    SalesAnalysisResult,
)

MAX_REPOSITORY_QUERIES_PER_INSIGHT = 1


class SalesPlanningError(RuntimeError):
    """A natural-language question could not be converted to a safe typed plan."""


@dataclass(frozen=True, slots=True)
class SalesInsight:
    """Transport-independent answer to a sales question."""

    answer: str
    next_cursor: str | None = None
    plan: SalesQueryPlan | None = None


@dataclass(frozen=True, slots=True)
class TopProduct:
    """A product ranked by the number of units sold in a period."""

    product_id: int
    sku: str
    name: str
    quantity_sold: int

    @classmethod
    def from_sales_total(cls, total: ProductSalesTotal) -> TopProduct:
        return cls(
            product_id=total.product_id,
            sku=total.sku,
            name=total.name,
            quantity_sold=total.quantity_sold,
        )


@dataclass(frozen=True, slots=True)
class SalesMonth:
    """Calendar month used as the reference for a sales result."""

    year: int
    month: int

    def __post_init__(self) -> None:
        if not 1 <= self.year <= 9999:
            raise ValueError("year deve estar entre 1 e 9999")
        if not 1 <= self.month <= 12:
            raise ValueError("month deve estar entre 1 e 12")


@dataclass(frozen=True, slots=True)
class TopProductsResult:
    """Top products and the calendar month from which they were calculated."""

    reference_month: SalesMonth | None
    products: tuple[TopProduct, ...]

    def __post_init__(self) -> None:
        if self.reference_month is None and self.products:
            raise ValueError("products exige um reference_month")


RepositoryQuery = AggregateSales | CompareSales
RepositoryRecord = SalesAnalysisResult


@dataclass(frozen=True, slots=True)
class SalesQueryPlan:
    """At most one repository operation selected from a closed catalog."""

    queries: tuple[RepositoryQuery, ...]

    def __post_init__(self) -> None:
        if len(self.queries) > MAX_REPOSITORY_QUERIES_PER_INSIGHT:
            raise ValueError("um plano de sales insight aceita no maximo uma consulta")


@dataclass(frozen=True, slots=True)
class RepositoryQueryResult:
    query: RepositoryQuery
    records: tuple[RepositoryRecord, ...]


@dataclass(frozen=True, slots=True)
class SalesQueryEvidence:
    """Facts already computed by deterministic application components."""

    results: tuple[RepositoryQueryResult, ...]
