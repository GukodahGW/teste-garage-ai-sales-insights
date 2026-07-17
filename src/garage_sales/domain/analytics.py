from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum


class SalesMetric(StrEnum):
    """Business metrics whose formulas are owned by the semantic layer."""

    REVENUE = "revenue"
    GROSS_REVENUE = "gross_revenue"
    NET_REVENUE = "net_revenue"
    SALE_COUNT = "sale_count"
    ORDER_COUNT = "order_count"
    UNITS_SOLD = "units_sold"
    AVERAGE_TICKET = "average_ticket"
    DISTINCT_CUSTOMERS = "distinct_customers"
    REFUND_AMOUNT = "refund_amount"
    REPEAT_CUSTOMER_RATE = "repeat_customer_rate"
    PURCHASE_FREQUENCY = "purchase_frequency"
    CUSTOMER_LIFETIME_VALUE = "customer_lifetime_value"


class SalesDimension(StrEnum):
    PRODUCT = "product"
    CATEGORY = "category"
    CUSTOMER = "customer"
    DAY = "day"
    WEEK = "week"
    MONTH = "month"
    QUARTER = "quarter"
    YEAR = "year"
    CURRENCY = "currency"
    CUSTOMER_SEGMENT = "customer_segment"


class SalesFilterField(StrEnum):
    PRODUCT = "product"
    CATEGORY = "category"
    CUSTOMER = "customer"
    ORDER_STATUS = "order_status"
    CURRENCY = "currency"
    CUSTOMER_SEGMENT = "customer_segment"


class FilterOperator(StrEnum):
    EQUALS = "equals"
    NOT_EQUALS = "not_equals"
    CONTAINS = "contains"
    IN = "in"


class ComparisonKind(StrEnum):
    CURRENT = "current"
    BASELINE = "baseline"
    ABSOLUTE_CHANGE = "absolute_change"
    PERCENTAGE_CHANGE = "percentage_change"


class SortDirection(StrEnum):
    ASCENDING = "ascending"
    DESCENDING = "descending"


class WindowKind(StrEnum):
    RANK = "rank"
    SHARE_OF_TOTAL = "share_of_total"
    CUMULATIVE = "cumulative"
    MOVING_AVERAGE = "moving_average"


class AssociationMetric(StrEnum):
    CO_PURCHASE_COUNT = "co_purchase_count"
    SUPPORT = "support"
    CONFIDENCE = "confidence"
    LIFT = "lift"


class CohortMetric(StrEnum):
    RETENTION_RATE = "retention_rate"
    ACTIVE_CUSTOMERS = "active_customers"
    REVENUE = "revenue"


class TimeGrain(StrEnum):
    DAY = "day"
    WEEK = "week"
    MONTH = "month"
    QUARTER = "quarter"
    YEAR = "year"


class AnalysisStatus(StrEnum):
    ANSWERED = "answered"
    NO_DATA = "no_data"
    UNSUPPORTED = "unsupported"
    AMBIGUOUS = "ambiguous"


class SalesAnalysisError(ValueError):
    """A validly parsed request whose business semantics cannot be executed safely."""


Scalar = Decimal | int | str | bool | None


@dataclass(frozen=True, slots=True)
class TimePeriod:
    """Half-open interval: start is inclusive and end is exclusive."""

    start: datetime | None = None
    end: datetime | None = None

    def __post_init__(self) -> None:
        for boundary in (self.start, self.end):
            if boundary is not None and boundary.utcoffset() is None:
                raise ValueError("limites de periodo devem conter fuso horario")
        if self.start is not None and self.end is not None and self.start >= self.end:
            raise ValueError("period.start deve ser anterior a period.end")

    @property
    def is_bounded(self) -> bool:
        return self.start is not None and self.end is not None


@dataclass(frozen=True, slots=True)
class SalesFilter:
    field: SalesFilterField
    operator: FilterOperator
    values: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.values:
            raise ValueError("um filtro deve conter ao menos um valor")
        if any(not value.strip() for value in self.values):
            raise ValueError("valores de filtro nao podem ser vazios")
        if len(set(self.values)) != len(self.values):
            raise ValueError("valores de filtro duplicados nao sao permitidos")
        if self.operator is not FilterOperator.IN and len(self.values) != 1:
            raise ValueError("somente o operador in aceita multiplos valores")
        if self.operator is FilterOperator.CONTAINS and self.field not in {
            SalesFilterField.PRODUCT,
            SalesFilterField.CATEGORY,
            SalesFilterField.CUSTOMER,
        }:
            raise ValueError("contains so pode filtrar produto, categoria ou cliente")
        if self.field is SalesFilterField.CUSTOMER_SEGMENT and any(
            value not in {"new", "repeat"} for value in self.values
        ):
            raise ValueError("customer_segment aceita apenas new ou repeat")


@dataclass(frozen=True, slots=True)
class MetricPredicate:
    metric: SalesMetric
    operator: str
    value: Decimal

    def __post_init__(self) -> None:
        if self.operator not in {"gt", "gte", "lt", "lte", "eq", "ne"}:
            raise ValueError("operador de metrica invalido")


@dataclass(frozen=True, slots=True)
class SortSpec:
    metric: SalesMetric
    direction: SortDirection = SortDirection.DESCENDING
    comparison: ComparisonKind | None = None


@dataclass(frozen=True, slots=True)
class WindowSpec:
    kind: WindowKind
    metric: SalesMetric
    partition_by: tuple[SalesDimension, ...] = ()
    size: int | None = None
    top_n: int | None = None

    def __post_init__(self) -> None:
        if len(set(self.partition_by)) != len(self.partition_by):
            raise ValueError("partition_by nao aceita dimensoes duplicadas")
        if self.kind is WindowKind.MOVING_AVERAGE:
            if self.size is None or not 2 <= self.size <= 365:
                raise ValueError("moving_average requer size entre 2 e 365")
        elif self.size is not None:
            raise ValueError("size so pode ser usado em moving_average")
        if self.kind is WindowKind.RANK:
            if self.top_n is not None and not 1 <= self.top_n <= 500:
                raise ValueError("top_n deve estar entre 1 e 500")
        elif self.top_n is not None:
            raise ValueError("top_n so pode ser usado em rank")


_TIME_DIMENSIONS = {
    SalesDimension.DAY,
    SalesDimension.WEEK,
    SalesDimension.MONTH,
    SalesDimension.QUARTER,
    SalesDimension.YEAR,
}
_ITEM_DIMENSIONS = {SalesDimension.PRODUCT, SalesDimension.CATEGORY}
_ITEM_FILTERS = {SalesFilterField.PRODUCT, SalesFilterField.CATEGORY}


def _validate_filters(filters: tuple[SalesFilter, ...]) -> None:
    if len(filters) > 12:
        raise ValueError("uma analise aceita no maximo 12 filtros")
    fields = tuple(item.field for item in filters)
    if len(set(fields)) != len(fields):
        raise ValueError("use um unico filtro por campo; combine valores com o operador in")


def _validate_dimensions(dimensions: tuple[SalesDimension, ...]) -> None:
    if len(dimensions) > 4 or len(set(dimensions)) != len(dimensions):
        raise ValueError("dimensoes devem ser unicas e limitadas a 4")
    if len(set(dimensions) & _TIME_DIMENSIONS) > 1:
        raise ValueError("uma consulta aceita no maximo uma granularidade temporal")


def _validate_metric_grain(
    metrics: tuple[SalesMetric, ...],
    dimensions: tuple[SalesDimension, ...],
    filters: tuple[SalesFilter, ...],
) -> None:
    requires_item_grain = bool(
        set(dimensions) & _ITEM_DIMENSIONS
        or {item.field for item in filters} & _ITEM_FILTERS
        or SalesMetric.UNITS_SOLD in metrics
    )
    if requires_item_grain and SalesMetric.AVERAGE_TICKET in metrics:
        raise ValueError(
            "average_ticket nao pode ser combinado com produto, categoria ou units_sold"
        )


def _require_bounded_period(period: TimePeriod, name: str) -> None:
    if not period.is_bounded:
        raise ValueError(f"{name} deve conter start e end")


def _validate_common_query(
    metrics: tuple[SalesMetric, ...],
    dimensions: tuple[SalesDimension, ...],
    filters: tuple[SalesFilter, ...],
    limit: int | None,
) -> None:
    if not 1 <= len(metrics) <= 8:
        raise ValueError("uma analise deve conter entre 1 e 8 metricas")
    if len(set(metrics)) != len(metrics):
        raise ValueError("metricas duplicadas nao sao permitidas")
    _validate_dimensions(dimensions)
    _validate_filters(filters)
    _validate_metric_grain(metrics, dimensions, filters)
    if limit is not None and not 1 <= limit <= 500:
        raise ValueError("limit deve estar entre 1 e 500")


@dataclass(frozen=True, slots=True)
class AggregateSales:
    metrics: tuple[SalesMetric, ...]
    dimensions: tuple[SalesDimension, ...] = ()
    filters: tuple[SalesFilter, ...] = ()
    period: TimePeriod = field(default_factory=TimePeriod)
    having: tuple[MetricPredicate, ...] = ()
    sort: tuple[SortSpec, ...] = ()
    windows: tuple[WindowSpec, ...] = ()
    limit: int | None = None
    include_totals: bool = False

    def __post_init__(self) -> None:
        _validate_common_query(self.metrics, self.dimensions, self.filters, self.limit)
        if len(self.having) > 8 or len(self.sort) > 4 or len(self.windows) > 4:
            raise ValueError("transformacoes excedem os limites da analise")
        if len(set(self.sort)) != len(self.sort):
            raise ValueError("criterios de ordenacao duplicados nao sao permitidos")
        if len(set(self.windows)) != len(self.windows):
            raise ValueError("janelas duplicadas nao sao permitidas")
        available = set(self.metrics)
        if any(item.metric not in available for item in self.having):
            raise ValueError("having e sort devem referenciar metricas selecionadas")
        if any(item.metric not in available for item in self.sort):
            raise ValueError("having e sort devem referenciar metricas selecionadas")
        if any(window.metric not in available for window in self.windows):
            raise ValueError("janelas devem referenciar metricas selecionadas")
        if any(item.comparison is not None for item in self.sort):
            raise ValueError("sort.comparison so pode ser usado em sales.compare")
        dimensions = set(self.dimensions)
        if self.windows and not dimensions:
            raise ValueError("janelas exigem ao menos uma dimensao")
        if any(not set(window.partition_by) <= dimensions for window in self.windows):
            raise ValueError("partition_by deve usar apenas dimensoes selecionadas")
        time_dimensions = dimensions & _TIME_DIMENSIONS
        for window in self.windows:
            if window.kind in {WindowKind.CUMULATIVE, WindowKind.MOVING_AVERAGE}:
                if len(time_dimensions) != 1:
                    raise ValueError("acumulado e media movel exigem uma dimensao temporal")
                if time_dimensions & set(window.partition_by):
                    raise ValueError("a dimensao temporal nao pode particionar sua propria serie")


@dataclass(frozen=True, slots=True)
class CompareSales:
    metrics: tuple[SalesMetric, ...]
    current_period: TimePeriod
    baseline_period: TimePeriod
    dimensions: tuple[SalesDimension, ...] = ()
    filters: tuple[SalesFilter, ...] = ()
    comparisons: tuple[ComparisonKind, ...] = (
        ComparisonKind.CURRENT,
        ComparisonKind.BASELINE,
        ComparisonKind.ABSOLUTE_CHANGE,
        ComparisonKind.PERCENTAGE_CHANGE,
    )
    sort: tuple[SortSpec, ...] = ()
    limit: int | None = None

    def __post_init__(self) -> None:
        _validate_common_query(self.metrics, self.dimensions, self.filters, self.limit)
        _require_bounded_period(self.current_period, "current_period")
        _require_bounded_period(self.baseline_period, "baseline_period")
        if self.current_period == self.baseline_period:
            raise ValueError("current_period e baseline_period devem ser diferentes")
        if not self.comparisons or len(set(self.comparisons)) != len(self.comparisons):
            raise ValueError("comparisons deve conter valores unicos")
        if any(item.metric not in set(self.metrics) for item in self.sort):
            raise ValueError("sort deve referenciar metricas selecionadas")
        if len(set(self.sort)) != len(self.sort):
            raise ValueError("criterios de ordenacao duplicados nao sao permitidos")
        if any(
            (item.comparison or ComparisonKind.CURRENT) not in self.comparisons
            for item in self.sort
        ):
            raise ValueError("sort deve usar uma comparacao solicitada")


@dataclass(frozen=True, slots=True)
class BasketAnalysis:
    period: TimePeriod = field(default_factory=TimePeriod)
    filters: tuple[SalesFilter, ...] = ()
    metric: AssociationMetric = AssociationMetric.LIFT
    minimum_orders: int = 2
    minimum_support: Decimal = Decimal("0")
    limit: int = 20

    def __post_init__(self) -> None:
        _validate_filters(self.filters)
        invalid_filters = {item.field for item in self.filters} & _ITEM_FILTERS
        if invalid_filters:
            raise ValueError("analise de cesta aceita filtros de cliente, status, moeda e segmento")
        if not 1 <= self.minimum_orders:
            raise ValueError("minimum_orders deve ser positivo")
        if not Decimal("0") <= self.minimum_support <= Decimal("1"):
            raise ValueError("minimum_support deve estar entre 0 e 1")
        if not 1 <= self.limit <= 100:
            raise ValueError("limit de cesta deve estar entre 1 e 100")


@dataclass(frozen=True, slots=True)
class CohortAnalysis:
    acquisition_period: TimePeriod
    activity_period: TimePeriod
    metric: CohortMetric = CohortMetric.RETENTION_RATE
    grain: TimeGrain = TimeGrain.MONTH
    filters: tuple[SalesFilter, ...] = ()
    limit: int = 120

    def __post_init__(self) -> None:
        _require_bounded_period(self.acquisition_period, "acquisition_period")
        _require_bounded_period(self.activity_period, "activity_period")
        _validate_filters(self.filters)
        if {item.field for item in self.filters} & _ITEM_FILTERS:
            raise ValueError("filtros de produto ou categoria nao sao validos para coorte")
        activity_end = self.activity_period.end
        acquisition_start = self.acquisition_period.start
        assert activity_end is not None and acquisition_start is not None
        if activity_end <= acquisition_start:
            raise ValueError("activity_period deve alcancar o periodo de aquisicao")
        if self.grain not in {TimeGrain.MONTH, TimeGrain.QUARTER, TimeGrain.YEAR}:
            raise ValueError("coortes suportam granularidade mensal, trimestral ou anual")
        if not 1 <= self.limit <= 500:
            raise ValueError("limit de coorte deve estar entre 1 e 500")


@dataclass(frozen=True, slots=True)
class ForecastSales:
    metric: SalesMetric
    history_period: TimePeriod
    grain: TimeGrain = TimeGrain.MONTH
    horizon: int = 3
    filters: tuple[SalesFilter, ...] = ()
    confidence: Decimal = Decimal("0.95")

    def __post_init__(self) -> None:
        _require_bounded_period(self.history_period, "history_period")
        _validate_filters(self.filters)
        if self.metric not in {
            SalesMetric.REVENUE,
            SalesMetric.GROSS_REVENUE,
            SalesMetric.NET_REVENUE,
            SalesMetric.ORDER_COUNT,
            SalesMetric.SALE_COUNT,
            SalesMetric.UNITS_SOLD,
        }:
            raise ValueError("metrica nao suportada para previsao")
        if not 1 <= self.horizon <= 36:
            raise ValueError("horizon deve estar entre 1 e 36")
        if not Decimal("0.5") <= self.confidence < Decimal("1"):
            raise ValueError("confidence deve estar entre 0.5 e 1")


@dataclass(frozen=True, slots=True)
class AnomalyAnalysis:
    metric: SalesMetric
    period: TimePeriod
    grain: TimeGrain = TimeGrain.DAY
    filters: tuple[SalesFilter, ...] = ()
    sensitivity: Decimal = Decimal("2.5")

    def __post_init__(self) -> None:
        _require_bounded_period(self.period, "period")
        _validate_filters(self.filters)
        _validate_metric_grain((self.metric,), (), self.filters)
        if not Decimal("1") <= self.sensitivity <= Decimal("5"):
            raise ValueError("sensitivity deve estar entre 1 e 5")


SalesAnalysisQuery = (
    AggregateSales
    | CompareSales
    | BasketAnalysis
    | CohortAnalysis
    | ForecastSales
    | AnomalyAnalysis
)


@dataclass(frozen=True, slots=True)
class AnalysisCell:
    name: str
    value: Scalar


@dataclass(frozen=True, slots=True)
class AnalysisRow:
    dimensions: tuple[AnalysisCell, ...] = ()
    metrics: tuple[AnalysisCell, ...] = ()

    def get_metric(self, name: str) -> Scalar:
        for cell in self.metrics:
            if cell.name == name:
                return cell.value
        return None


@dataclass(frozen=True, slots=True)
class AnalysisDataset:
    rows: tuple[AnalysisRow, ...]
    status: AnalysisStatus = AnalysisStatus.ANSWERED
    warnings: tuple[str, ...] = ()
    metadata: tuple[AnalysisCell, ...] = ()
