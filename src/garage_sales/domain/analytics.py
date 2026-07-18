from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

Scalar = Decimal | int | str | None


class SalesMetric(StrEnum):
    REVENUE = "revenue"
    SALE_COUNT = "sale_count"
    UNITS_SOLD = "units_sold"
    AVERAGE_TICKET = "average_ticket"


class SalesDimension(StrEnum):
    PRODUCT = "product"
    CATEGORY = "category"
    CUSTOMER = "customer"
    DAY = "day"
    WEEK = "week"
    MONTH = "month"
    YEAR = "year"


class SalesFilterField(StrEnum):
    PRODUCT = "product"
    CATEGORY = "category"
    CUSTOMER = "customer"


class FilterOperator(StrEnum):
    EQUALS = "equals"
    CONTAINS = "contains"
    IN = "in"


class SortDirection(StrEnum):
    ASCENDING = "asc"
    DESCENDING = "desc"


class ComparisonKind(StrEnum):
    CURRENT = "current"
    BASELINE = "baseline"
    ABSOLUTE_CHANGE = "absolute_change"
    PERCENTAGE_CHANGE = "percentage_change"


@dataclass(frozen=True, slots=True)
class TimePeriod:
    start: datetime | None = None
    end: datetime | None = None

    def __post_init__(self) -> None:
        if self.start and self.end and self.start > self.end:
            raise ValueError("period.start nao pode ser posterior a period.end")

    @property
    def is_bounded(self) -> bool:
        return self.start is not None and self.end is not None


@dataclass(frozen=True, slots=True)
class SalesFilter:
    field: SalesFilterField
    values: tuple[str, ...]
    operator: FilterOperator = FilterOperator.EQUALS

    def __post_init__(self) -> None:
        if not self.values or len(self.values) > 20:
            raise ValueError("um filtro deve conter entre 1 e 20 valores")
        if any(not value.strip() for value in self.values):
            raise ValueError("valores de filtro nao podem ser vazios")
        if len(set(self.values)) != len(self.values):
            raise ValueError("valores de filtro duplicados nao sao permitidos")
        if self.operator is not FilterOperator.IN and len(self.values) != 1:
            raise ValueError("somente o operador in aceita multiplos valores")


@dataclass(frozen=True, slots=True)
class SortSpec:
    metric: SalesMetric
    direction: SortDirection = SortDirection.DESCENDING
    comparison: ComparisonKind | None = None


_TIME_DIMENSIONS = {
    SalesDimension.DAY,
    SalesDimension.WEEK,
    SalesDimension.MONTH,
    SalesDimension.YEAR,
}


def _validate_common(
    metrics: tuple[SalesMetric, ...],
    dimensions: tuple[SalesDimension, ...],
    filters: tuple[SalesFilter, ...],
    sort: tuple[SortSpec, ...],
    limit: int | None,
) -> None:
    if not 1 <= len(metrics) <= 4 or len(set(metrics)) != len(metrics):
        raise ValueError("metrics deve conter entre 1 e 4 valores unicos")
    if len(dimensions) > 2 or len(set(dimensions)) != len(dimensions):
        raise ValueError("dimensions deve conter no maximo 2 valores unicos")
    if len(set(dimensions) & _TIME_DIMENSIONS) > 1:
        raise ValueError("uma consulta aceita no maximo uma dimensao temporal")
    if len(filters) > 6 or len({item.field for item in filters}) != len(filters):
        raise ValueError("filters deve conter no maximo um filtro por campo")
    if len(sort) > 2 or len(set(sort)) != len(sort):
        raise ValueError("sort deve conter no maximo 2 criterios unicos")
    if any(item.metric not in metrics for item in sort):
        raise ValueError("sort deve referenciar uma metrica selecionada")
    if limit is not None and not 1 <= limit <= 100:
        raise ValueError("limit deve estar entre 1 e 100")
    if limit is not None and not dimensions:
        raise ValueError("limit exige ao menos uma dimensao")


@dataclass(frozen=True, slots=True)
class AggregateSales:
    metrics: tuple[SalesMetric, ...]
    dimensions: tuple[SalesDimension, ...] = ()
    filters: tuple[SalesFilter, ...] = ()
    period: TimePeriod = field(default_factory=TimePeriod)
    sort: tuple[SortSpec, ...] = ()
    limit: int | None = None

    def __post_init__(self) -> None:
        _validate_common(self.metrics, self.dimensions, self.filters, self.sort, self.limit)
        if any(item.comparison is not None for item in self.sort):
            raise ValueError("sort.comparison so pode ser usado em sales.compare")


@dataclass(frozen=True, slots=True)
class CompareSales:
    metrics: tuple[SalesMetric, ...]
    current_period: TimePeriod
    baseline_period: TimePeriod
    dimensions: tuple[SalesDimension, ...] = ()
    filters: tuple[SalesFilter, ...] = ()
    sort: tuple[SortSpec, ...] = ()
    limit: int | None = None

    def __post_init__(self) -> None:
        _validate_common(self.metrics, self.dimensions, self.filters, self.sort, self.limit)
        if not self.current_period.is_bounded or not self.baseline_period.is_bounded:
            raise ValueError("sales.compare exige periodos completos")
        if self.current_period == self.baseline_period:
            raise ValueError("current_period e baseline_period devem ser diferentes")


class SalesAnalysisCursorError(ValueError):
    """An opaque analytics cursor is invalid for the requested comparison."""


SalesAnalysisQuery = AggregateSales | CompareSales


@dataclass(frozen=True, slots=True)
class AnalysisCell:
    name: str
    value: Scalar


@dataclass(frozen=True, slots=True)
class AnalysisRow:
    dimensions: tuple[AnalysisCell, ...] = ()
    metrics: tuple[AnalysisCell, ...] = ()

    def dimension_key(self) -> tuple[Scalar, ...]:
        return tuple(cell.value for cell in self.dimensions)

    def metric_value(self, name: str) -> Scalar:
        for cell in self.metrics:
            if cell.name == name:
                return cell.value
        return None


@dataclass(frozen=True, slots=True)
class SalesAnalysisResult:
    rows: tuple[AnalysisRow, ...]
    next_cursor: str | None = None

    def __post_init__(self) -> None:
        if self.next_cursor is not None and not self.next_cursor:
            raise ValueError("next_cursor nao pode ser vazio")


@dataclass(frozen=True, slots=True)
class ProductSalesTotal:
    product_id: int
    sku: str
    name: str
    quantity_sold: int
