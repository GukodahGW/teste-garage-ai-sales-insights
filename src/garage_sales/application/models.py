from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from garage_sales.domain.analytics import (
    AggregateSales,
    AnalysisDataset,
    AnalysisStatus,
    AnomalyAnalysis,
    BasketAnalysis,
    CohortAnalysis,
    CompareSales,
    ForecastSales,
    SalesMetric,
)

MAX_REPOSITORY_QUERIES_PER_INSIGHT = 5


class SalesPlanningError(RuntimeError):
    """A natural-language question could not be converted to a safe typed plan."""


@dataclass(frozen=True, slots=True)
class SalesInsight:
    """Transport-independent, auditable result for a sales question."""

    answer: str
    status: AnalysisStatus = AnalysisStatus.ANSWERED
    data: tuple[AnalysisDataset, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class TopProduct:
    """A product ranked by the number of units sold in a period."""

    product_id: int
    sku: str
    name: str
    quantity_sold: int


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


@dataclass(frozen=True, slots=True)
class CalculateSalesMetric:
    """Calculate one fundamental sales metric over a closed time interval."""

    metric: SalesMetric
    sold_from: datetime | None = None
    sold_until: datetime | None = None

    def __post_init__(self) -> None:
        if self.metric not in {
            SalesMetric.REVENUE,
            SalesMetric.SALE_COUNT,
            SalesMetric.UNITS_SOLD,
            SalesMetric.AVERAGE_TICKET,
        }:
            raise ValueError("sales.calculate aceita apenas metricas legadas fundamentais")
        if self.sold_from and self.sold_until and self.sold_from > self.sold_until:
            raise ValueError("sold_from nao pode ser posterior a sold_until")


@dataclass(frozen=True, slots=True)
class FindTopProducts:
    """Rank products deterministically by units sold in a time interval."""

    sold_from: datetime | None = None
    sold_until: datetime | None = None
    limit: int = 5

    def __post_init__(self) -> None:
        if not 1 <= self.limit <= 20:
            raise ValueError("limit de top products deve estar entre 1 e 20")
        if self.sold_from and self.sold_until and self.sold_from > self.sold_until:
            raise ValueError("sold_from nao pode ser posterior a sold_until")


@dataclass(frozen=True, slots=True)
class SalesMetricValue:
    """Value computed by deterministic application code, never by a model."""

    metric: SalesMetric
    value: Decimal | int
    matched_sales: int

    def __post_init__(self) -> None:
        if self.matched_sales < 0:
            raise ValueError("matched_sales nao pode ser negativo")
        monetary_metrics = {SalesMetric.REVENUE, SalesMetric.AVERAGE_TICKET}
        if self.metric in monetary_metrics and not isinstance(self.value, Decimal):
            raise TypeError("metricas monetarias devem usar Decimal")
        if self.metric not in monetary_metrics and (
            not isinstance(self.value, int) or isinstance(self.value, bool)
        ):
            raise TypeError("metricas de contagem devem usar int")


RepositoryQuery = (
    CalculateSalesMetric
    | FindTopProducts
    | AggregateSales
    | CompareSales
    | BasketAnalysis
    | CohortAnalysis
    | ForecastSales
    | AnomalyAnalysis
)
RepositoryRecord = SalesMetricValue | TopProduct | AnalysisDataset


@dataclass(frozen=True, slots=True)
class SalesQueryPlan:
    """Bounded analytical program produced from one natural-language question."""

    queries: tuple[RepositoryQuery, ...]

    def __post_init__(self) -> None:
        if len(self.queries) > MAX_REPOSITORY_QUERIES_PER_INSIGHT:
            raise ValueError(
                "um plano de sales insight deve conter no maximo "
                f"{MAX_REPOSITORY_QUERIES_PER_INSIGHT} consultas"
            )
        if len(set(self.queries)) != len(self.queries):
            raise ValueError("um plano nao pode conter consultas duplicadas")
        legacy = (CalculateSalesMetric, FindTopProducts)
        if len(self.queries) > 1 and any(isinstance(query, legacy) for query in self.queries):
            raise ValueError("operacoes legadas nao podem compor um plano")


@dataclass(frozen=True, slots=True)
class RepositoryQueryResult:
    query: RepositoryQuery
    records: tuple[RepositoryRecord, ...]


@dataclass(frozen=True, slots=True)
class SalesQueryEvidence:
    """Facts already computed by deterministic application components."""

    results: tuple[RepositoryQueryResult, ...]
