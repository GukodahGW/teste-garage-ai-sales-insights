import base64
import binascii
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal, DecimalException
from typing import Any

from sqlalchemy import and_, case, false, func, literal, null, or_, select, true
from sqlalchemy.orm import Session

from garage_sales.domain.analytics import (
    AggregateSales,
    AnalysisCell,
    AnalysisRow,
    CompareSales,
    ComparisonKind,
    FilterOperator,
    ProductSalesTotal,
    SalesAnalysisCursorError,
    SalesAnalysisResult,
    SalesDimension,
    SalesFilter,
    SalesFilterField,
    SalesMetric,
    SortDirection,
)
from garage_sales.infrastructure.sqlalchemy.models import (
    CustomerModel,
    ProductModel,
    SaleModel,
)

MONEY_QUANTUM = Decimal("0.01")
PERCENT_QUANTUM = Decimal("0.0001")
COMPARE_PAGE_SIZE = 100
MAX_CURSOR_LENGTH = 4_096
CURSOR_VERSION = 1


@dataclass(frozen=True, slots=True)
class _DimensionBinding:
    name: str
    value: Any
    group_by: tuple[Any, ...]
    identity: tuple[Any, ...] = ()


@dataclass(frozen=True, slots=True)
class _OrderTerm:
    expression: Any
    direction: SortDirection


class SqlAlchemySalesAnalyticsRepository:
    """Compile bounded analytics to SQL over sales, products, and customers."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._dialect = session.get_bind().dialect.name

    def aggregate(self, query: AggregateSales) -> SalesAnalysisResult:
        bindings = tuple(self._dimension_binding(item) for item in query.dimensions)
        metric_expressions = {
            metric: self._metric_expression(metric).label(metric.value) for metric in query.metrics
        }
        matched_sales = func.count(SaleModel.id).label("_matched_sales")
        statement = select(
            *(binding.value.label(binding.name) for binding in bindings),
            *(metric_expressions[metric] for metric in query.metrics),
            matched_sales,
        ).select_from(self._base_from(query))

        if query.period.start is not None:
            statement = statement.where(SaleModel.sold_at >= query.period.start)
        if query.period.end is not None:
            statement = statement.where(SaleModel.sold_at <= query.period.end)
        for filter_spec in query.filters:
            statement = statement.where(self._filter_condition(filter_spec))

        group_by = tuple(column for binding in bindings for column in binding.group_by)
        if group_by:
            statement = statement.group_by(*group_by)

        if query.sort:
            for sort_spec in query.sort:
                expression = metric_expressions[sort_spec.metric]
                statement = statement.order_by(
                    expression.asc()
                    if sort_spec.direction is SortDirection.ASCENDING
                    else expression.desc()
                )
            statement = statement.order_by(*(binding.value.asc() for binding in bindings))
        elif bindings:
            statement = statement.order_by(*(binding.value.asc() for binding in bindings))
        if query.limit is not None:
            statement = statement.limit(query.limit)

        rows: list[AnalysisRow] = []
        dimension_count = len(bindings)
        metric_count = len(query.metrics)
        for raw_row in self._session.execute(statement):
            if int(raw_row[dimension_count + metric_count]) == 0:
                continue
            dimensions = tuple(
                AnalysisCell(binding.name, str(raw_row[index]))
                for index, binding in enumerate(bindings)
            )
            metrics = tuple(
                AnalysisCell(
                    metric.value,
                    self._metric_value(metric, raw_row[dimension_count + index]),
                )
                for index, metric in enumerate(query.metrics)
            )
            rows.append(AnalysisRow(dimensions=dimensions, metrics=metrics))
        return SalesAnalysisResult(rows=tuple(rows))

    def compare(
        self,
        query: CompareSales,
        *,
        cursor: str | None = None,
    ) -> SalesAnalysisResult:
        """Compare two periods in one grouped statement and return one keyset page."""

        bindings = tuple(self._dimension_binding(item) for item in query.dimensions)
        current_start = query.current_period.start
        current_end = query.current_period.end
        baseline_start = query.baseline_period.start
        baseline_end = query.baseline_period.end
        assert current_start is not None and current_end is not None
        assert baseline_start is not None and baseline_end is not None
        current_condition = and_(
            SaleModel.sold_at >= current_start,
            SaleModel.sold_at <= current_end,
        )
        baseline_condition = and_(
            SaleModel.sold_at >= baseline_start,
            SaleModel.sold_at <= baseline_end,
        )

        inner_columns = [binding.value.label(binding.name) for binding in bindings]
        identity_names: list[str] = []
        for binding_index, binding in enumerate(bindings):
            for identity_index, expression in enumerate(binding.identity):
                name = f"_identity_{binding_index}_{identity_index}"
                identity_names.append(name)
                inner_columns.append(expression.label(name))

        for metric in query.metrics:
            inner_columns.extend(
                (
                    self._conditional_metric_expression(metric, current_condition).label(
                        f"{metric.value}_current"
                    ),
                    self._conditional_metric_expression(metric, baseline_condition).label(
                        f"{metric.value}_baseline"
                    ),
                )
            )
        inner_columns.append(func.count(SaleModel.id).label("_matched_sales"))

        grouped = select(*inner_columns).select_from(self._base_from(query))
        grouped = grouped.where(or_(current_condition, baseline_condition))
        for filter_spec in query.filters:
            grouped = grouped.where(self._filter_condition(filter_spec))

        group_by = tuple(column for binding in bindings for column in binding.group_by)
        if group_by:
            grouped = grouped.group_by(*group_by)
        comparison = grouped.subquery("sales_comparison")

        output_columns = [comparison.c[binding.name] for binding in bindings]
        sortable: dict[tuple[SalesMetric, ComparisonKind], Any] = {}
        for metric in query.metrics:
            current = comparison.c[f"{metric.value}_current"]
            baseline = comparison.c[f"{metric.value}_baseline"]
            absolute = current - baseline
            percentage = case(
                (baseline == 0, null()),
                else_=func.round(absolute * 100 / func.abs(baseline), 4),
            )
            expressions = {
                ComparisonKind.CURRENT: current,
                ComparisonKind.BASELINE: baseline,
                ComparisonKind.ABSOLUTE_CHANGE: absolute,
                ComparisonKind.PERCENTAGE_CHANGE: percentage,
            }
            for comparison_kind, expression in expressions.items():
                output_columns.append(
                    expression.label(f"{metric.value}.{comparison_kind.value}")
                )
                sortable[metric, comparison_kind] = expression

        order_terms: list[_OrderTerm] = []
        for item in query.sort:
            comparison_kind = item.comparison or ComparisonKind.PERCENTAGE_CHANGE
            expression = sortable[item.metric, comparison_kind]
            order_terms.extend(
                (
                    _OrderTerm(
                        case((expression.is_(None), 1), else_=0),
                        SortDirection.ASCENDING,
                    ),
                    _OrderTerm(expression, item.direction),
                )
            )
        order_terms.extend(
            _OrderTerm(comparison.c[binding.name], SortDirection.ASCENDING)
            for binding in bindings
        )
        order_terms.extend(
            _OrderTerm(comparison.c[name], SortDirection.ASCENDING)
            for name in identity_names
        )

        cursor_values: tuple[Any, ...] = ()
        consumed = 0
        if cursor is not None:
            cursor_values, consumed = _decode_cursor(cursor, query)
            if len(cursor_values) != len(order_terms):
                raise SalesAnalysisCursorError("cursor incompativel com a ordenacao")

        remaining = None if query.limit is None else query.limit - consumed
        if remaining is not None and remaining <= 0:
            raise SalesAnalysisCursorError("cursor aponta para alem do limite da consulta")
        page_size = COMPARE_PAGE_SIZE if remaining is None else min(COMPARE_PAGE_SIZE, remaining)

        cursor_columns = [
            term.expression.label(f"_cursor_{index}")
            for index, term in enumerate(order_terms)
        ]
        statement = (
            select(*output_columns, *cursor_columns)
            .select_from(comparison)
            .where(comparison.c._matched_sales > 0)
        )
        if cursor_values:
            statement = statement.where(_keyset_condition(order_terms, cursor_values))
        statement = statement.order_by(
            *(
                term.expression.asc()
                if term.direction is SortDirection.ASCENDING
                else term.expression.desc()
                for term in order_terms
            )
        )

        can_continue = query.limit is None or remaining is not None and remaining > page_size
        fetch_size = page_size + 1 if can_continue and order_terms else page_size
        raw_rows = list(self._session.execute(statement.limit(fetch_size)))
        has_more = len(raw_rows) > page_size
        page_rows = raw_rows[:page_size]

        rows = tuple(self._comparison_row(query, bindings, raw_row) for raw_row in page_rows)
        next_cursor = None
        if has_more and page_rows:
            mapping = page_rows[-1]._mapping
            next_cursor = _encode_cursor(
                query,
                tuple(mapping[f"_cursor_{index}"] for index in range(len(order_terms))),
                consumed + len(page_rows),
            )
        return SalesAnalysisResult(rows=rows, next_cursor=next_cursor)

    @classmethod
    def _comparison_row(
        cls,
        query: CompareSales,
        bindings: tuple[_DimensionBinding, ...],
        raw_row: Any,
    ) -> AnalysisRow:
        mapping = raw_row._mapping
        dimensions = tuple(
            AnalysisCell(binding.name, str(mapping[binding.name])) for binding in bindings
        )
        metrics: list[AnalysisCell] = []
        for metric in query.metrics:
            for comparison_kind in (
                ComparisonKind.CURRENT,
                ComparisonKind.BASELINE,
                ComparisonKind.ABSOLUTE_CHANGE,
            ):
                name = f"{metric.value}.{comparison_kind.value}"
                metrics.append(AnalysisCell(name, cls._metric_value(metric, mapping[name])))
            percentage_name = f"{metric.value}.{ComparisonKind.PERCENTAGE_CHANGE.value}"
            percentage = mapping[percentage_name]
            metrics.append(
                AnalysisCell(
                    percentage_name,
                    None
                    if percentage is None
                    else Decimal(str(percentage)).quantize(
                        PERCENT_QUANTUM,
                        rounding=ROUND_HALF_UP,
                    ),
                )
            )
        return AnalysisRow(dimensions=dimensions, metrics=tuple(metrics))

    def top_products(
        self,
        *,
        sold_from: datetime | None = None,
        sold_until: datetime | None = None,
        limit: int = 5,
    ) -> tuple[ProductSalesTotal, ...]:
        quantity_sold = func.sum(SaleModel.quantity).label("quantity_sold")
        statement = (
            select(ProductModel.id, ProductModel.sku, ProductModel.name, quantity_sold)
            .join(SaleModel, SaleModel.product_id == ProductModel.id)
            .where(SaleModel.quantity > 0)
            .group_by(ProductModel.id, ProductModel.sku, ProductModel.name)
            .order_by(quantity_sold.desc(), ProductModel.id.asc())
            .limit(limit)
        )
        if sold_from is not None:
            statement = statement.where(SaleModel.sold_at >= sold_from)
        if sold_until is not None:
            statement = statement.where(SaleModel.sold_at <= sold_until)
        return tuple(
            ProductSalesTotal(
                product_id=int(product_id),
                sku=str(sku),
                name=str(name),
                quantity_sold=int(total),
            )
            for product_id, sku, name, total in self._session.execute(statement)
        )

    @staticmethod
    def _base_from(query: AggregateSales | CompareSales) -> Any:
        requires_product = bool(
            set(query.dimensions) & {SalesDimension.PRODUCT, SalesDimension.CATEGORY}
            or {item.field for item in query.filters}
            & {SalesFilterField.PRODUCT, SalesFilterField.CATEGORY}
        )
        requires_customer = bool(
            SalesDimension.CUSTOMER in query.dimensions
            or SalesFilterField.CUSTOMER in {item.field for item in query.filters}
        )
        base: Any = SaleModel.__table__
        if requires_product:
            base = base.outerjoin(ProductModel.__table__, ProductModel.id == SaleModel.product_id)
        if requires_customer:
            base = base.outerjoin(
                CustomerModel.__table__, CustomerModel.id == SaleModel.customer_id
            )
        return base

    def _dimension_binding(self, dimension: SalesDimension) -> _DimensionBinding:
        if dimension is SalesDimension.PRODUCT:
            value = func.coalesce(ProductModel.name, literal("Produto desconhecido"))
            return _DimensionBinding(
                dimension.value,
                value,
                (ProductModel.id, value),
                (ProductModel.id,),
            )
        if dimension is SalesDimension.CATEGORY:
            value = func.coalesce(ProductModel.category, literal("Sem categoria"))
            return _DimensionBinding(dimension.value, value, (value,))
        if dimension is SalesDimension.CUSTOMER:
            value = func.coalesce(CustomerModel.name, literal("Cliente não identificado"))
            return _DimensionBinding(
                dimension.value,
                value,
                (CustomerModel.id, value),
                (CustomerModel.id,),
            )
        value = self._time_bucket(SaleModel.sold_at, dimension)
        return _DimensionBinding(dimension.value, value, (value,))

    def _time_bucket(self, column: Any, dimension: SalesDimension) -> Any:
        if dimension is SalesDimension.DAY:
            formats = ("%Y-%m-%d", "YYYY-MM-DD", "%Y-%m-%d")
        elif dimension is SalesDimension.WEEK:
            formats = ("%G-W%V", 'IYYY-"W"IW', "%x-W%v")
        elif dimension is SalesDimension.MONTH:
            formats = ("%Y-%m", "YYYY-MM", "%Y-%m")
        elif dimension is SalesDimension.YEAR:
            formats = ("%Y", "YYYY", "%Y")
        else:
            raise ValueError(f"dimensao temporal nao suportada: {dimension.value}")
        if self._dialect == "sqlite":
            return func.strftime(formats[0], column)
        if self._dialect == "postgresql":
            return func.to_char(column, formats[1])
        return func.date_format(column, formats[2])

    @staticmethod
    def _metric_expression(metric: SalesMetric) -> Any:
        if metric is SalesMetric.REVENUE:
            return func.coalesce(func.sum(SaleModel.total_amount), Decimal("0.00"))
        if metric is SalesMetric.SALE_COUNT:
            return func.count(SaleModel.id)
        if metric is SalesMetric.UNITS_SOLD:
            return func.coalesce(func.sum(SaleModel.quantity), 0)
        if metric is SalesMetric.AVERAGE_TICKET:
            return func.coalesce(func.avg(SaleModel.total_amount), Decimal("0.00"))
        raise ValueError(f"metrica nao suportada: {metric.value}")

    @staticmethod
    def _conditional_metric_expression(metric: SalesMetric, condition: Any) -> Any:
        if metric is SalesMetric.REVENUE:
            return func.coalesce(
                func.sum(
                    case(
                        (condition, SaleModel.total_amount),
                        else_=Decimal("0.00"),
                    )
                ),
                Decimal("0.00"),
            )
        if metric is SalesMetric.SALE_COUNT:
            return func.coalesce(func.sum(case((condition, 1), else_=0)), 0)
        if metric is SalesMetric.UNITS_SOLD:
            return func.coalesce(
                func.sum(case((condition, SaleModel.quantity), else_=0)),
                0,
            )
        if metric is SalesMetric.AVERAGE_TICKET:
            return func.coalesce(
                func.avg(case((condition, SaleModel.total_amount))),
                Decimal("0.00"),
            )
        raise ValueError(f"metrica nao suportada: {metric.value}")

    @staticmethod
    def _metric_value(metric: SalesMetric, value: Any) -> Decimal | int:
        if metric in {SalesMetric.REVENUE, SalesMetric.AVERAGE_TICKET}:
            return Decimal(str(value)).quantize(MONEY_QUANTUM)
        return int(value)

    @staticmethod
    def _filter_condition(item: SalesFilter) -> Any:
        if item.field is SalesFilterField.PRODUCT:
            columns: tuple[Any, ...] = (ProductModel.name, ProductModel.sku)
        elif item.field is SalesFilterField.CATEGORY:
            columns = (ProductModel.category,)
        elif item.field is SalesFilterField.CUSTOMER:
            columns = (CustomerModel.name, CustomerModel.email)
        else:
            raise ValueError(f"filtro nao suportado: {item.field.value}")

        values = tuple(value.lower() for value in item.values)
        conditions: list[Any] = []
        for column in columns:
            lowered = func.lower(column)
            if item.operator is FilterOperator.EQUALS:
                conditions.append(lowered == values[0])
            elif item.operator is FilterOperator.CONTAINS:
                conditions.append(lowered.contains(values[0], autoescape=True))
            elif item.operator is FilterOperator.IN:
                conditions.append(lowered.in_(values))
            else:
                raise ValueError(f"operador nao suportado: {item.operator.value}")
        return or_(*conditions)


def _cursor_fingerprint(query: CompareSales) -> str:
    return hashlib.sha256(repr(query).encode("utf-8")).hexdigest()


def _encode_cursor(
    query: CompareSales,
    values: tuple[Any, ...],
    consumed: int,
) -> str:
    payload = {
        "v": CURSOR_VERSION,
        "q": _cursor_fingerprint(query),
        "n": consumed,
        "k": [_pack_cursor_value(value) for value in values],
    }
    encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(encoded).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str, query: CompareSales) -> tuple[tuple[Any, ...], int]:
    if not cursor or len(cursor) > MAX_CURSOR_LENGTH:
        raise SalesAnalysisCursorError("cursor invalido")
    try:
        padding = "=" * (-len(cursor) % 4)
        encoded = (cursor + padding).encode("ascii")
        payload = json.loads(
            base64.b64decode(encoded, altchars=b"-_", validate=True).decode("utf-8")
        )
        if not isinstance(payload, dict):
            raise TypeError
        if set(payload) != {"v", "q", "n", "k"}:
            raise TypeError
        if payload.get("v") != CURSOR_VERSION:
            raise ValueError
        if payload.get("q") != _cursor_fingerprint(query):
            raise SalesAnalysisCursorError("cursor pertence a outra consulta")
        consumed = payload.get("n")
        keys = payload.get("k")
        if isinstance(consumed, bool) or not isinstance(consumed, int) or consumed < 1:
            raise TypeError
        if not isinstance(keys, list):
            raise TypeError
        values = tuple(_unpack_cursor_value(value) for value in keys)
    except SalesAnalysisCursorError:
        raise
    except (
        binascii.Error,
        DecimalException,
        KeyError,
        TypeError,
        UnicodeError,
        ValueError,
        json.JSONDecodeError,
    ) as error:
        raise SalesAnalysisCursorError("cursor invalido") from error
    return values, consumed


def _pack_cursor_value(value: Any) -> dict[str, Any]:
    if value is None:
        return {"t": "null"}
    if isinstance(value, bool):
        raise TypeError("boolean cursor keys are not supported")
    if isinstance(value, int):
        return {"t": "int", "v": value}
    if isinstance(value, (Decimal, float)):
        return {"t": "decimal", "v": str(value)}
    if isinstance(value, str):
        return {"t": "string", "v": value}
    raise TypeError(f"unsupported cursor key: {type(value).__name__}")


def _unpack_cursor_value(value: Any) -> Any:
    if not isinstance(value, dict):
        raise TypeError
    value_type = value.get("t")
    if value_type == "null" and set(value) == {"t"}:
        return None
    if set(value) != {"t", "v"}:
        raise TypeError
    raw_value = value["v"]
    if value_type == "int" and isinstance(raw_value, int) and not isinstance(raw_value, bool):
        return raw_value
    if value_type == "decimal" and isinstance(raw_value, str):
        decimal_value = Decimal(raw_value)
        if decimal_value.is_finite():
            return decimal_value
    if value_type == "string" and isinstance(raw_value, str):
        return raw_value
    raise TypeError


def _keyset_condition(
    order_terms: list[_OrderTerm],
    values: tuple[Any, ...],
) -> Any:
    clauses: list[Any] = []
    equal_prefix: Any = true()
    for term, value in zip(order_terms, values, strict=True):
        if value is not None:
            comparison = (
                term.expression > value
                if term.direction is SortDirection.ASCENDING
                else term.expression < value
            )
            clauses.append(and_(equal_prefix, comparison))
            equality = term.expression == value
        else:
            equality = term.expression.is_(None)
        equal_prefix = and_(equal_prefix, equality)
    return or_(*clauses) if clauses else false()
