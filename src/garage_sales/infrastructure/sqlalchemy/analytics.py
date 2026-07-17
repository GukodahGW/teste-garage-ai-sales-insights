from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from math import sqrt
from typing import Any, cast

from sqlalchemy import (
    Select,
    and_,
    case,
    func,
    literal,
    select,
)
from sqlalchemy import (
    cast as sql_cast,
)
from sqlalchemy.orm import Session, aliased
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.types import Integer, String

from garage_sales.domain.analytics import (
    AggregateSales,
    AnalysisCell,
    AnalysisDataset,
    AnalysisRow,
    AnalysisStatus,
    AnomalyAnalysis,
    AssociationMetric,
    BasketAnalysis,
    CohortAnalysis,
    CohortMetric,
    CompareSales,
    ComparisonKind,
    FilterOperator,
    ForecastSales,
    MetricPredicate,
    SalesAnalysisError,
    SalesAnalysisQuery,
    SalesDimension,
    SalesFilter,
    SalesFilterField,
    SalesMetric,
    Scalar,
    SortDirection,
    TimeGrain,
    TimePeriod,
    WindowKind,
    WindowSpec,
)
from garage_sales.infrastructure.sqlalchemy.models import (
    CategoryModel,
    CustomerModel,
    OrderItemModel,
    OrderModel,
    ProductModel,
    RefundModel,
)

MONEY = Decimal("0.01")
PERCENT = Decimal("0.0001")
MONETARY_METRICS = {
    SalesMetric.REVENUE,
    SalesMetric.GROSS_REVENUE,
    SalesMetric.NET_REVENUE,
    SalesMetric.AVERAGE_TICKET,
    SalesMetric.REFUND_AMOUNT,
    SalesMetric.CUSTOMER_LIFETIME_VALUE,
}
ITEM_DIMENSIONS = {SalesDimension.PRODUCT, SalesDimension.CATEGORY}


class SalesSemanticError(SalesAnalysisError):
    """A structurally valid plan whose requested semantics are unsafe."""


@dataclass(frozen=True, slots=True)
class _DimensionBinding:
    name: str
    value: Any
    group_by: tuple[Any, ...]


class SqlAlchemySalesAnalyticsRepository:
    """Compile the closed analytical algebra to parameterized SQLAlchemy queries."""

    def __init__(self, session: Session) -> None:
        self._session = session
        bind = session.get_bind()
        self._dialect = bind.dialect.name

    def execute(self, query: SalesAnalysisQuery) -> AnalysisDataset:
        resolution = self._validate_entity_filters(getattr(query, "filters", ()))
        if resolution is not None:
            return resolution
        if isinstance(query, AggregateSales):
            return self._aggregate(query)
        if isinstance(query, CompareSales):
            return self._compare(query)
        if isinstance(query, BasketAnalysis):
            return self._basket(query)
        if isinstance(query, CohortAnalysis):
            return self._cohort(query)
        if isinstance(query, ForecastSales):
            return self._forecast(query)
        if isinstance(query, AnomalyAnalysis):
            return self._anomalies(query)
        raise TypeError(f"consulta analitica desconhecida: {type(query).__name__}")

    def _validate_entity_filters(
        self,
        filters: tuple[SalesFilter, ...],
    ) -> AnalysisDataset | None:
        for item in filters:
            if item.operator is FilterOperator.IN:
                continue
            value = item.values[0]
            statement: Any
            column: Any
            if item.field is SalesFilterField.PRODUCT:
                statement = select(ProductModel.id, ProductModel.name)
                column = ProductModel.name
            elif item.field is SalesFilterField.CUSTOMER:
                statement = select(CustomerModel.id, CustomerModel.name)
                column = CustomerModel.name
            elif item.field is SalesFilterField.CATEGORY:
                statement = select(ProductModel.category, ProductModel.category).distinct()
                column = ProductModel.category
            else:
                continue
            condition = self._filter_condition(column, item)
            matches = list(self._session.execute(statement.where(condition)).all())
            if not matches:
                return AnalysisDataset(
                    rows=(),
                    status=AnalysisStatus.NO_DATA,
                    warnings=(f"Nenhum {item.field.value} corresponde a '{value}'.",),
                )
            identifiers = {str(row[0]) for row in matches}
            if len(identifiers) > 1:
                candidates = ", ".join(sorted({str(row[1]) for row in matches})[:10])
                return AnalysisDataset(
                    rows=(),
                    status=AnalysisStatus.AMBIGUOUS,
                    warnings=(
                        f"'{value}' corresponde a mais de um {item.field.value}: {candidates}.",
                    ),
                )
        return None

    def _aggregate(self, query: AggregateSales) -> AnalysisDataset:
        item_grain = self._requires_item_grain(query)
        if item_grain and SalesMetric.AVERAGE_TICKET in query.metrics:
            raise SalesSemanticError(
                "average_ticket possui grao de pedido e nao pode ser combinado com "
                "produto/categoria sem uma regra explicita de atribuicao"
            )
        warnings = list(self._currency_warnings(query, item_grain))
        bindings = [self._dimension_binding(item, item_grain) for item in query.dimensions]
        metrics = {
            metric: self._metric_expression(metric, item_grain).label(metric.value)
            for metric in query.metrics
        }

        statement = select(
            *(binding.value.label(binding.name) for binding in bindings),
            *metrics.values(),
        ).select_from(self._base_from(item_grain))
        statement = self._apply_common_filters(
            statement,
            period=query.period,
            filters=query.filters,
            item_grain=item_grain,
        )
        group_columns = tuple(expression for binding in bindings for expression in binding.group_by)
        if group_columns:
            statement = statement.group_by(*group_columns)
        for predicate in query.having:
            statement = statement.having(self._predicate(metrics[predicate.metric], predicate))
        for sort_item in query.sort:
            expression = metrics[sort_item.metric]
            statement = statement.order_by(
                expression.asc()
                if sort_item.direction is SortDirection.ASCENDING
                else expression.desc()
            )
        if bindings:
            statement = statement.order_by(*(binding.value.asc() for binding in bindings))
        if query.limit is not None:
            statement = statement.limit(query.limit)

        rows = self._rows_from_result(statement, bindings, query.metrics)
        if item_grain and SalesMetric.NET_REVENUE in query.metrics:
            warnings.append(
                "Receita liquida por produto/categoria considera estornos vinculados ao item; "
                "estornos sem item permanecem no nivel do pedido."
            )

        if query.include_totals and query.dimensions:
            total_query = replace(
                query,
                dimensions=(),
                having=(),
                sort=(),
                windows=(),
                limit=None,
                include_totals=False,
            )
            total = self._aggregate(total_query)
            rows = rows + tuple(
                AnalysisRow(
                    dimensions=(AnalysisCell("row_type", "total"),),
                    metrics=row.metrics,
                )
                for row in total.rows
            )

        rows = self._apply_windows(rows, query.windows)
        status = AnalysisStatus.ANSWERED if rows else AnalysisStatus.NO_DATA
        return AnalysisDataset(
            rows=rows,
            status=status,
            warnings=tuple(warnings),
            metadata=(
                AnalysisCell("analysis", "aggregate"),
                AnalysisCell("metrics", ",".join(item.value for item in query.metrics)),
                AnalysisCell("dimensions", ",".join(item.value for item in query.dimensions)),
                *self._period_metadata(query.period),
            ),
        )

    @staticmethod
    def _requires_item_grain(query: AggregateSales | CompareSales) -> bool:
        return bool(
            set(query.dimensions) & ITEM_DIMENSIONS
            or any(
                item.field in {SalesFilterField.PRODUCT, SalesFilterField.CATEGORY}
                for item in query.filters
            )
            or SalesMetric.UNITS_SOLD in query.metrics
        )

    def _base_from(self, item_grain: bool) -> Any:
        if item_grain:
            return (
                OrderModel.__table__.join(
                    OrderItemModel.__table__, OrderItemModel.order_id == OrderModel.id
                )
                .outerjoin(ProductModel.__table__, ProductModel.id == OrderItemModel.product_id)
                .outerjoin(CategoryModel.__table__, CategoryModel.id == ProductModel.category_id)
                .outerjoin(CustomerModel.__table__, CustomerModel.id == OrderModel.customer_id)
            )
        return OrderModel.__table__.outerjoin(
            CustomerModel.__table__, CustomerModel.id == OrderModel.customer_id
        )

    def _dimension_binding(
        self,
        dimension: SalesDimension,
        item_grain: bool,
    ) -> _DimensionBinding:
        if dimension in ITEM_DIMENSIONS and not item_grain:
            raise SalesSemanticError(f"a dimensao {dimension.value} exige o grao de item")
        if dimension is SalesDimension.PRODUCT:
            value: Any = func.coalesce(
                OrderItemModel.product_name,
                ProductModel.name,
                literal("Produto desconhecido"),
            )
            return _DimensionBinding(
                dimension.value,
                value,
                (OrderItemModel.product_id, value),
            )
        if dimension is SalesDimension.CATEGORY:
            value = func.coalesce(
                OrderItemModel.category_name,
                CategoryModel.name,
                ProductModel.category,
                literal("Sem categoria"),
            )
            return _DimensionBinding(dimension.value, value, (value,))
        if dimension is SalesDimension.CUSTOMER:
            value = func.coalesce(CustomerModel.name, literal("Cliente nao identificado"))
            return _DimensionBinding(
                dimension.value,
                value,
                (OrderModel.customer_id, value),
            )
        if dimension is SalesDimension.CUSTOMER_SEGMENT:
            value = self._customer_segment_expression()
            return _DimensionBinding(dimension.value, value, (value,))
        if dimension is SalesDimension.CURRENCY:
            return _DimensionBinding(dimension.value, OrderModel.currency, (OrderModel.currency,))
        if dimension in {
            SalesDimension.DAY,
            SalesDimension.WEEK,
            SalesDimension.MONTH,
            SalesDimension.QUARTER,
            SalesDimension.YEAR,
        }:
            bucket_value = self._time_bucket(OrderModel.ordered_at, dimension.value)
            return _DimensionBinding(dimension.value, bucket_value, (bucket_value,))
        raise SalesSemanticError(f"dimensao nao suportada: {dimension.value}")

    def _time_bucket(self, column: Any, grain: str) -> ColumnElement[str]:
        formats = {
            "day": ("%Y-%m-%d", "YYYY-MM-DD", "%Y-%m-%d"),
            "month": ("%Y-%m", "YYYY-MM", "%Y-%m"),
            "year": ("%Y", "YYYY", "%Y"),
        }
        if grain == "quarter":
            year = sql_cast(func.extract("year", column), Integer)
            quarter = sql_cast((func.extract("month", column) - 1) / 3 + 1, Integer)
            if self._dialect == "sqlite":
                return sql_cast(year, String) + literal("-Q") + sql_cast(quarter, String)
            return func.concat(year, literal("-Q"), quarter)
        if grain == "week":
            if self._dialect == "sqlite":
                return func.strftime("%Y-W%W", column)
            if self._dialect == "postgresql":
                return func.to_char(column, 'IYYY-"W"IW')
            return func.date_format(column, "%x-W%v")
        sqlite_format, postgres_format, mysql_format = formats[grain]
        if self._dialect == "sqlite":
            return func.strftime(sqlite_format, column)
        if self._dialect == "postgresql":
            return func.to_char(column, postgres_format)
        return func.date_format(column, mysql_format)

    def _metric_expression(
        self,
        metric: SalesMetric,
        item_grain: bool,
    ) -> ColumnElement[Any]:
        order_count = func.count(func.distinct(OrderModel.id))
        if metric in {SalesMetric.SALE_COUNT, SalesMetric.ORDER_COUNT}:
            return order_count
        if metric is SalesMetric.UNITS_SOLD:
            if not item_grain:
                raise SalesSemanticError("units_sold exige o grao de item")
            return func.coalesce(func.sum(OrderItemModel.quantity), 0)
        if metric is SalesMetric.DISTINCT_CUSTOMERS:
            return func.count(func.distinct(OrderModel.customer_id))
        distinct_customers = func.count(func.distinct(OrderModel.customer_id))
        if metric is SalesMetric.PURCHASE_FREQUENCY:
            return case(
                (distinct_customers == 0, Decimal("0")),
                else_=order_count / distinct_customers,
            )
        if metric is SalesMetric.REPEAT_CUSTOMER_RATE:
            repeat_customers = func.count(
                func.distinct(
                    case(
                        (
                            self._customer_order_count_expression() >= 2,
                            OrderModel.customer_id,
                        ),
                        else_=None,
                    )
                )
            )
            return case(
                (distinct_customers == 0, Decimal("0")),
                else_=repeat_customers * 100 / distinct_customers,
            )
        if metric is SalesMetric.GROSS_REVENUE:
            amount = (
                OrderItemModel.net_amount + OrderItemModel.discount_amount
                if item_grain
                else OrderModel.gross_amount
            )
            return func.coalesce(func.sum(amount), Decimal("0.00"))
        if metric is SalesMetric.REVENUE:
            amount = OrderItemModel.net_amount if item_grain else OrderModel.net_amount
            return func.coalesce(func.sum(amount), Decimal("0.00"))
        if metric is SalesMetric.NET_REVENUE:
            amount = OrderItemModel.net_amount if item_grain else OrderModel.net_amount
            if item_grain:
                refund = (
                    select(func.coalesce(func.sum(RefundModel.amount), Decimal("0.00")))
                    .where(RefundModel.order_item_id == OrderItemModel.id)
                    .correlate(OrderItemModel)
                    .scalar_subquery()
                )
            else:
                refund = (
                    select(func.coalesce(func.sum(RefundModel.amount), Decimal("0.00")))
                    .where(RefundModel.order_id == OrderModel.id)
                    .correlate(OrderModel)
                    .scalar_subquery()
                )
            return func.coalesce(func.sum(amount - refund), Decimal("0.00"))
        if metric is SalesMetric.AVERAGE_TICKET:
            amount = OrderItemModel.net_amount if item_grain else OrderModel.net_amount
            return case(
                (order_count == 0, Decimal("0.00")),
                else_=func.sum(amount) / order_count,
            )
        if metric is SalesMetric.CUSTOMER_LIFETIME_VALUE:
            amount = OrderItemModel.net_amount if item_grain else OrderModel.net_amount
            return case(
                (distinct_customers == 0, Decimal("0.00")),
                else_=func.sum(amount) / distinct_customers,
            )
        if metric is SalesMetric.REFUND_AMOUNT:
            refund = (
                select(func.coalesce(func.sum(RefundModel.amount), Decimal("0.00")))
                .where(RefundModel.order_id == OrderModel.id)
                .correlate(OrderModel)
                .scalar_subquery()
            )
            if item_grain:
                refund = (
                    select(func.coalesce(func.sum(RefundModel.amount), Decimal("0.00")))
                    .where(RefundModel.order_item_id == OrderItemModel.id)
                    .correlate(OrderItemModel)
                    .scalar_subquery()
                )
            return func.coalesce(func.sum(refund), Decimal("0.00"))
        raise SalesSemanticError(f"metrica nao suportada: {metric.value}")

    def _apply_common_filters(
        self,
        statement: Select[Any],
        *,
        period: TimePeriod,
        filters: tuple[SalesFilter, ...],
        item_grain: bool,
    ) -> Select[Any]:
        conditions: list[ColumnElement[bool]] = [OrderModel.status != "cancelled"]
        if period.start is not None:
            conditions.append(OrderModel.ordered_at >= period.start)
        if period.end is not None:
            conditions.append(OrderModel.ordered_at < period.end)
        for item in filters:
            column: Any
            if item.field is SalesFilterField.PRODUCT:
                if not item_grain:
                    raise SalesSemanticError("filtro de produto exige o grao de item")
                column = func.coalesce(OrderItemModel.product_name, ProductModel.name)
            elif item.field is SalesFilterField.CATEGORY:
                if not item_grain:
                    raise SalesSemanticError("filtro de categoria exige o grao de item")
                column = func.coalesce(
                    OrderItemModel.category_name,
                    CategoryModel.name,
                    ProductModel.category,
                )
            elif item.field is SalesFilterField.CUSTOMER:
                column = CustomerModel.name
            elif item.field is SalesFilterField.ORDER_STATUS:
                column = OrderModel.status
            elif item.field is SalesFilterField.CURRENCY:
                column = OrderModel.currency
            elif item.field is SalesFilterField.CUSTOMER_SEGMENT:
                column = self._customer_segment_expression()
            else:
                raise SalesSemanticError(f"filtro nao suportado: {item.field.value}")
            conditions.append(self._filter_condition(column, item))
        return statement.where(and_(*conditions))

    def _customer_order_count_expression(self) -> ColumnElement[int]:
        history_order = aliased(OrderModel)
        return (
            select(func.count(history_order.id))
            .where(
                history_order.customer_id == OrderModel.customer_id,
                history_order.status != "cancelled",
            )
            .correlate(OrderModel)
            .scalar_subquery()
        )

    def _customer_segment_expression(self) -> ColumnElement[str]:
        return case(
            (OrderModel.customer_id.is_(None), literal("unidentified")),
            (self._customer_order_count_expression() >= 2, literal("repeat")),
            else_=literal("new"),
        )

    @staticmethod
    def _filter_condition(
        column: Any,
        item: SalesFilter,
    ) -> ColumnElement[bool]:
        value = item.values[0]
        if item.operator is FilterOperator.EQUALS:
            return cast(ColumnElement[bool], column == value)
        if item.operator is FilterOperator.NOT_EQUALS:
            return cast(ColumnElement[bool], column != value)
        if item.operator is FilterOperator.CONTAINS:
            return cast(ColumnElement[bool], column.icontains(value, autoescape=True))
        if item.operator is FilterOperator.IN:
            return cast(ColumnElement[bool], column.in_(item.values))
        raise SalesSemanticError(f"operador de filtro nao suportado: {item.operator.value}")

    @staticmethod
    def _predicate(
        expression: ColumnElement[Any],
        predicate: MetricPredicate,
    ) -> ColumnElement[bool]:
        operators = {
            "gt": expression > predicate.value,
            "gte": expression >= predicate.value,
            "lt": expression < predicate.value,
            "lte": expression <= predicate.value,
            "eq": expression == predicate.value,
            "ne": expression != predicate.value,
        }
        return operators[predicate.operator]

    def _rows_from_result(
        self,
        statement: Select[Any],
        bindings: list[_DimensionBinding],
        metrics: tuple[SalesMetric, ...],
    ) -> tuple[AnalysisRow, ...]:
        rows: list[AnalysisRow] = []
        for result in self._session.execute(statement).mappings():
            rows.append(
                AnalysisRow(
                    dimensions=tuple(
                        AnalysisCell(binding.name, self._normalize(result[binding.name]))
                        for binding in bindings
                    ),
                    metrics=tuple(
                        AnalysisCell(
                            metric.value,
                            self._normalize_metric(result[metric.value], metric),
                        )
                        for metric in metrics
                    ),
                )
            )
        return tuple(rows)

    @staticmethod
    def _normalize_metric(value: Any, metric: SalesMetric) -> Scalar:
        if isinstance(value, Decimal) and metric in {
            SalesMetric.REPEAT_CUSTOMER_RATE,
            SalesMetric.PURCHASE_FREQUENCY,
        }:
            return value.quantize(PERCENT, rounding=ROUND_HALF_UP)
        return SqlAlchemySalesAnalyticsRepository._normalize(value)

    @staticmethod
    def _normalize(value: Any) -> Scalar:
        if isinstance(value, Decimal):
            return value.quantize(MONEY, rounding=ROUND_HALF_UP)
        if isinstance(value, (str, int, bool)) or value is None:
            return value
        if isinstance(value, float):
            return Decimal(str(value)).quantize(PERCENT, rounding=ROUND_HALF_UP)
        return str(value)

    def _currency_warnings(
        self,
        query: AggregateSales,
        item_grain: bool,
    ) -> tuple[str, ...]:
        if not set(query.metrics) & MONETARY_METRICS:
            return ()
        if SalesDimension.CURRENCY in query.dimensions or any(
            item.field is SalesFilterField.CURRENCY for item in query.filters
        ):
            return ()
        statement = select(func.count(func.distinct(OrderModel.currency))).select_from(
            self._base_from(item_grain)
        )
        statement = self._apply_common_filters(
            statement,
            period=query.period,
            filters=query.filters,
            item_grain=item_grain,
        )
        if (self._session.scalar(statement) or 0) > 1:
            raise SalesSemanticError(
                "metricas monetarias de moedas diferentes exigem filtro ou dimensao currency"
            )
        return ()

    def _compare(self, query: CompareSales) -> AnalysisDataset:
        current = self._aggregate(
            AggregateSales(
                metrics=query.metrics,
                dimensions=query.dimensions,
                filters=query.filters,
                period=query.current_period,
            )
        )
        baseline = self._aggregate(
            AggregateSales(
                metrics=query.metrics,
                dimensions=query.dimensions,
                filters=query.filters,
                period=query.baseline_period,
            )
        )
        current_by_key = {self._dimension_key(row): row for row in current.rows}
        baseline_by_key = {self._dimension_key(row): row for row in baseline.rows}
        keys = sorted(set(current_by_key) | set(baseline_by_key))
        output: list[AnalysisRow] = []
        for key in keys:
            current_row = current_by_key.get(key)
            baseline_row = baseline_by_key.get(key)
            dimensions = (
                current_row.dimensions
                if current_row is not None
                else cast(AnalysisRow, baseline_row).dimensions
            )
            cells: list[AnalysisCell] = []
            for metric in query.metrics:
                current_value = self._numeric_metric(current_row, metric)
                baseline_value = self._numeric_metric(baseline_row, metric)
                absolute = current_value - baseline_value
                percentage = (
                    None
                    if baseline_value == 0
                    else (absolute / abs(baseline_value) * 100).quantize(PERCENT)
                )
                values: dict[ComparisonKind, Scalar] = {
                    ComparisonKind.CURRENT: current_value,
                    ComparisonKind.BASELINE: baseline_value,
                    ComparisonKind.ABSOLUTE_CHANGE: absolute,
                    ComparisonKind.PERCENTAGE_CHANGE: percentage,
                }
                cells.extend(
                    AnalysisCell(f"{metric.value}.{kind.value}", values[kind])
                    for kind in query.comparisons
                )
            output.append(AnalysisRow(dimensions=dimensions, metrics=tuple(cells)))

        for sort_item in reversed(query.sort):
            suffix = (sort_item.comparison or ComparisonKind.CURRENT).value
            name = f"{sort_item.metric.value}.{suffix}"
            output.sort(
                key=lambda row: self._sortable(row.get_metric(name)),
                reverse=sort_item.direction is SortDirection.DESCENDING,
            )
        if query.limit is not None:
            output = output[: query.limit]
        warnings = tuple(dict.fromkeys((*current.warnings, *baseline.warnings)))
        status = AnalysisStatus.ANSWERED if output else AnalysisStatus.NO_DATA
        return AnalysisDataset(
            rows=tuple(output),
            status=status,
            warnings=warnings,
            metadata=(
                AnalysisCell("analysis", "compare"),
                AnalysisCell("metrics", ",".join(item.value for item in query.metrics)),
                *self._period_metadata(query.current_period, "current_period"),
                *self._period_metadata(query.baseline_period, "baseline_period"),
            ),
        )

    @staticmethod
    def _dimension_key(row: AnalysisRow) -> tuple[tuple[str, str], ...]:
        return tuple((cell.name, str(cell.value)) for cell in row.dimensions)

    @staticmethod
    def _numeric_metric(row: AnalysisRow | None, metric: SalesMetric) -> Decimal:
        if row is None:
            return Decimal("0")
        value = row.get_metric(metric.value)
        if isinstance(value, Decimal):
            return value
        if isinstance(value, int) and not isinstance(value, bool):
            return Decimal(value)
        return Decimal("0")

    @staticmethod
    def _sortable(value: Scalar) -> tuple[bool, Decimal | str]:
        if value is None:
            return (False, Decimal("0"))
        if isinstance(value, Decimal):
            return (True, value)
        if isinstance(value, int) and not isinstance(value, bool):
            return (True, Decimal(value))
        return (True, str(value))

    def _basket(self, query: BasketAnalysis) -> AnalysisDataset:
        left = aliased(OrderItemModel, name="basket_left")
        right = aliased(OrderItemModel, name="basket_right")
        base_conditions: list[ColumnElement[bool]] = [OrderModel.status != "cancelled"]
        pair_conditions: list[ColumnElement[bool]] = [
            left.order_id == right.order_id,
            left.product_id.is_not(None),
            right.product_id.is_not(None),
            left.product_id < right.product_id,
        ]
        if query.period.start is not None:
            base_conditions.append(OrderModel.ordered_at >= query.period.start)
        if query.period.end is not None:
            base_conditions.append(OrderModel.ordered_at < query.period.end)
        for item in query.filters:
            if item.field in {SalesFilterField.ORDER_STATUS, SalesFilterField.CURRENCY}:
                column = (
                    OrderModel.status
                    if item.field is SalesFilterField.ORDER_STATUS
                    else OrderModel.currency
                )
                base_conditions.append(self._filter_condition(column, item))
            elif item.field is SalesFilterField.CUSTOMER:
                base_conditions.append(self._filter_condition(CustomerModel.name, item))
            elif item.field is SalesFilterField.CUSTOMER_SEGMENT:
                base_conditions.append(
                    self._filter_condition(self._customer_segment_expression(), item)
                )
            else:
                raise SalesSemanticError(
                    "analise de cesta aceita filtros de cliente, status, moeda e periodo"
                )

        total_orders_statement = (
            select(func.count(func.distinct(OrderModel.id)))
            .select_from(OrderModel)
            .outerjoin(CustomerModel, CustomerModel.id == OrderModel.customer_id)
            .where(and_(*base_conditions))
        )
        total_orders = int(self._session.scalar(total_orders_statement) or 0)
        if total_orders == 0:
            return AnalysisDataset(rows=(), status=AnalysisStatus.NO_DATA)

        pair_count = func.count(func.distinct(OrderModel.id)).label("pair_orders")
        statement = (
            select(
                left.product_id.label("left_id"),
                func.max(left.product_name).label("left_name"),
                right.product_id.label("right_id"),
                func.max(right.product_name).label("right_name"),
                pair_count,
            )
            .select_from(OrderModel)
            .join(left, left.order_id == OrderModel.id)
            .join(right, right.order_id == OrderModel.id)
            .outerjoin(CustomerModel, CustomerModel.id == OrderModel.customer_id)
            .where(and_(*base_conditions, *pair_conditions))
            .group_by(left.product_id, right.product_id)
            .having(pair_count >= query.minimum_orders)
        )
        pair_rows = list(self._session.execute(statement).mappings())
        product_order_counts: dict[int | None, int] = {
            row["product_id"]: int(row["order_count"])
            for row in self._session.execute(
                select(
                    OrderItemModel.product_id.label("product_id"),
                    func.count(func.distinct(OrderItemModel.order_id)).label("order_count"),
                )
                .join(OrderModel, OrderModel.id == OrderItemModel.order_id)
                .outerjoin(CustomerModel, CustomerModel.id == OrderModel.customer_id)
                .where(and_(*base_conditions))
                .group_by(OrderItemModel.product_id)
            ).mappings()
        }
        output: list[AnalysisRow] = []
        for row in pair_rows:
            pairs = int(row["pair_orders"])
            left_orders = int(product_order_counts.get(row["left_id"], 0))
            right_orders = int(product_order_counts.get(row["right_id"], 0))
            support = (Decimal(pairs) / total_orders).quantize(PERCENT)
            if support < query.minimum_support:
                continue
            confidence = (
                Decimal("0")
                if left_orders == 0
                else (Decimal(pairs) / left_orders).quantize(PERCENT)
            )
            denominator = Decimal(left_orders * right_orders)
            lift = (
                Decimal("0")
                if denominator == 0
                else (Decimal(pairs * total_orders) / denominator).quantize(PERCENT)
            )
            metric_values = {
                AssociationMetric.CO_PURCHASE_COUNT: Decimal(pairs),
                AssociationMetric.SUPPORT: support,
                AssociationMetric.CONFIDENCE: confidence,
                AssociationMetric.LIFT: lift,
            }
            output.append(
                AnalysisRow(
                    dimensions=(
                        AnalysisCell("product_a", row["left_name"] or row["left_id"]),
                        AnalysisCell("product_b", row["right_name"] or row["right_id"]),
                    ),
                    metrics=(
                        AnalysisCell("co_purchase_count", pairs),
                        AnalysisCell("support", support),
                        AnalysisCell("confidence", confidence),
                        AnalysisCell("lift", lift),
                        AnalysisCell("selected_metric", metric_values[query.metric]),
                    ),
                )
            )
        output.sort(
            key=lambda row: self._sortable(row.get_metric("selected_metric")),
            reverse=True,
        )
        output = output[: query.limit]
        status = AnalysisStatus.ANSWERED if output else AnalysisStatus.NO_DATA
        return AnalysisDataset(
            rows=tuple(output),
            status=status,
            metadata=(
                AnalysisCell("analysis", "basket"),
                AnalysisCell("eligible_orders", total_orders),
                *self._period_metadata(query.period),
            ),
        )

    def _cohort(self, query: CohortAnalysis) -> AnalysisDataset:
        if any(
            item.field in {SalesFilterField.PRODUCT, SalesFilterField.CATEGORY}
            for item in query.filters
        ):
            raise SalesSemanticError("filtros de produto/categoria nao sao validos para coorte")
        first_order = (
            select(
                OrderModel.customer_id.label("customer_id"),
                func.min(OrderModel.ordered_at).label("acquired_at"),
            )
            .where(
                OrderModel.customer_id.is_not(None),
                OrderModel.status != "cancelled",
            )
            .group_by(OrderModel.customer_id)
            .subquery("first_order")
        )
        cohort_bucket = self._time_bucket(first_order.c.acquired_at, query.grain.value)
        activity_bucket = self._time_bucket(OrderModel.ordered_at, query.grain.value)
        active = func.count(func.distinct(OrderModel.customer_id)).label("active_customers")
        revenue = func.coalesce(func.sum(OrderModel.net_amount), Decimal("0.00")).label("revenue")
        statement = (
            select(
                cohort_bucket.label("cohort"),
                activity_bucket.label("activity_period"),
                active,
                revenue,
            )
            .select_from(OrderModel)
            .join(first_order, first_order.c.customer_id == OrderModel.customer_id)
            .outerjoin(CustomerModel, CustomerModel.id == OrderModel.customer_id)
            .where(OrderModel.status != "cancelled")
        )
        for item in query.filters:
            if item.field is SalesFilterField.CUSTOMER:
                statement = statement.where(self._filter_condition(CustomerModel.name, item))
            elif item.field is SalesFilterField.ORDER_STATUS:
                statement = statement.where(self._filter_condition(OrderModel.status, item))
            elif item.field is SalesFilterField.CURRENCY:
                statement = statement.where(self._filter_condition(OrderModel.currency, item))
            elif item.field is SalesFilterField.CUSTOMER_SEGMENT:
                statement = statement.where(
                    self._filter_condition(self._customer_segment_expression(), item)
                )
        if query.acquisition_period.start is not None:
            statement = statement.where(first_order.c.acquired_at >= query.acquisition_period.start)
        if query.acquisition_period.end is not None:
            statement = statement.where(first_order.c.acquired_at < query.acquisition_period.end)
        if query.activity_period.start is not None:
            statement = statement.where(OrderModel.ordered_at >= query.activity_period.start)
        if query.activity_period.end is not None:
            statement = statement.where(OrderModel.ordered_at < query.activity_period.end)
        statement = statement.group_by(cohort_bucket, activity_bucket).order_by(
            cohort_bucket, activity_bucket
        )
        raw = list(self._session.execute(statement.limit(query.limit)).mappings())
        size_statement = select(
            cohort_bucket.label("cohort"),
            func.count(first_order.c.customer_id).label("cohort_size"),
        ).select_from(first_order)
        if query.acquisition_period.start is not None:
            size_statement = size_statement.where(
                first_order.c.acquired_at >= query.acquisition_period.start
            )
        if query.acquisition_period.end is not None:
            size_statement = size_statement.where(
                first_order.c.acquired_at < query.acquisition_period.end
            )
        size_statement = size_statement.group_by(cohort_bucket)
        cohort_sizes = {
            str(row["cohort"]): int(row["cohort_size"])
            for row in self._session.execute(size_statement).mappings()
        }
        output: list[AnalysisRow] = []
        for row in raw:
            cohort = str(row["cohort"])
            active_customers = int(row["active_customers"])
            size = cohort_sizes[cohort]
            retention = (
                Decimal("0")
                if size == 0
                else (Decimal(active_customers) / size * 100).quantize(PERCENT)
            )
            selected: Scalar
            if query.metric is CohortMetric.RETENTION_RATE:
                selected = retention
            elif query.metric is CohortMetric.ACTIVE_CUSTOMERS:
                selected = active_customers
            else:
                selected = self._normalize(row["revenue"])
            output.append(
                AnalysisRow(
                    dimensions=(
                        AnalysisCell("cohort", cohort),
                        AnalysisCell("activity_period", self._normalize(row["activity_period"])),
                    ),
                    metrics=(
                        AnalysisCell("cohort_size", size),
                        AnalysisCell("active_customers", active_customers),
                        AnalysisCell("retention_rate", retention),
                        AnalysisCell("revenue", self._normalize(row["revenue"])),
                        AnalysisCell("selected_metric", selected),
                    ),
                )
            )
        status = AnalysisStatus.ANSWERED if output else AnalysisStatus.NO_DATA
        return AnalysisDataset(
            rows=tuple(output),
            status=status,
            metadata=(
                AnalysisCell("analysis", "cohort"),
                *self._period_metadata(query.acquisition_period, "acquisition_period"),
                *self._period_metadata(query.activity_period, "activity_period"),
            ),
        )

    def _forecast(self, query: ForecastSales) -> AnalysisDataset:
        dimension = self._dimension_for_grain(query.grain)
        history = self._aggregate(
            AggregateSales(
                metrics=(query.metric,),
                dimensions=(dimension,),
                filters=query.filters,
                period=query.history_period,
                sort=(),
                limit=500,
            )
        )
        points = [self._numeric_metric(row, query.metric) for row in history.rows]
        if len(points) < 3:
            return AnalysisDataset(
                rows=(),
                status=AnalysisStatus.UNSUPPORTED,
                warnings=("Previsao requer ao menos tres periodos agregados.",),
            )
        count = len(points)
        training = points[:-1]
        training_count = len(training)
        training_mean_x = Decimal(training_count - 1) / 2
        training_mean_y = sum(training, Decimal("0")) / training_count
        training_denominator = sum(
            (Decimal(index) - training_mean_x) ** 2 for index in range(training_count)
        )
        training_slope = (
            Decimal("0")
            if training_denominator == 0
            else sum(
                (Decimal(index) - training_mean_x) * (value - training_mean_y)
                for index, value in enumerate(training)
            )
            / training_denominator
        )
        training_intercept = training_mean_y - training_slope * training_mean_x
        backtest_prediction = training_intercept + training_slope * training_count
        backtest_error = (
            None
            if points[-1] == 0
            else (abs(points[-1] - backtest_prediction) / abs(points[-1]) * 100).quantize(PERCENT)
        )
        mean_x = Decimal(count - 1) / 2
        mean_y = sum(points, Decimal("0")) / count
        denominator = sum((Decimal(index) - mean_x) ** 2 for index in range(count))
        slope = (
            Decimal("0")
            if denominator == 0
            else sum(
                (Decimal(index) - mean_x) * (value - mean_y) for index, value in enumerate(points)
            )
            / denominator
        )
        intercept = mean_y - slope * mean_x
        residuals = [
            float(value - (intercept + slope * index)) for index, value in enumerate(points)
        ]
        standard_error = Decimal(
            str(sqrt(sum(item * item for item in residuals) / max(1, count - 2)))
        )
        z = self._z_score(query.confidence)
        last_period = str(history.rows[-1].dimensions[0].value)
        output: list[AnalysisRow] = []
        for step in range(1, query.horizon + 1):
            prediction = (intercept + slope * (count - 1 + step)).quantize(MONEY)
            margin = (standard_error * z * Decimal(str(sqrt(1 + step / count)))).quantize(MONEY)
            output.append(
                AnalysisRow(
                    dimensions=(
                        AnalysisCell(
                            dimension.value,
                            self._advance_bucket(last_period, query.grain, step),
                        ),
                    ),
                    metrics=(
                        AnalysisCell("forecast", max(prediction, Decimal("0"))),
                        AnalysisCell("lower_bound", max(prediction - margin, Decimal("0"))),
                        AnalysisCell("upper_bound", max(prediction + margin, Decimal("0"))),
                    ),
                )
            )
        return AnalysisDataset(
            rows=tuple(output),
            warnings=(
                "Previsao por tendencia linear; valores sao estimativas, nao fatos observados.",
            ),
            metadata=(
                AnalysisCell("analysis", "forecast"),
                AnalysisCell("metric", query.metric.value),
                *self._period_metadata(query.history_period, "history_period"),
                AnalysisCell("confidence", query.confidence),
                AnalysisCell("backtest_points", count),
                AnalysisCell("backtest_absolute_percentage_error", backtest_error),
            ),
        )

    def _anomalies(self, query: AnomalyAnalysis) -> AnalysisDataset:
        dimension = self._dimension_for_grain(query.grain)
        series = self._aggregate(
            AggregateSales(
                metrics=(query.metric,),
                dimensions=(dimension,),
                filters=query.filters,
                period=query.period,
                limit=500,
            )
        )
        values = [self._numeric_metric(row, query.metric) for row in series.rows]
        if len(values) < 3:
            return AnalysisDataset(
                rows=(),
                status=AnalysisStatus.UNSUPPORTED,
                warnings=("Deteccao de anomalias requer ao menos tres periodos.",),
            )
        mean = sum(values, Decimal("0")) / len(values)
        variance = sum((value - mean) ** 2 for value in values) / len(values)
        deviation = Decimal(str(sqrt(float(variance))))
        output: list[AnalysisRow] = []
        if deviation != 0:
            for row, value in zip(series.rows, values, strict=True):
                score = ((value - mean) / deviation).quantize(PERCENT)
                if abs(score) >= query.sensitivity:
                    output.append(
                        AnalysisRow(
                            dimensions=row.dimensions,
                            metrics=(
                                AnalysisCell("actual", value),
                                AnalysisCell("expected", mean.quantize(MONEY)),
                                AnalysisCell("z_score", score),
                            ),
                        )
                    )
        return AnalysisDataset(
            rows=tuple(output),
            status=AnalysisStatus.ANSWERED,
            warnings=(
                "Anomalias usam desvio padrao historico e indicam diferenca, nao causalidade.",
            ),
            metadata=(
                AnalysisCell("analysis", "anomalies"),
                AnalysisCell("metric", query.metric.value),
                *self._period_metadata(query.period),
            ),
        )

    @staticmethod
    def _period_metadata(
        period: TimePeriod,
        prefix: str = "period",
    ) -> tuple[AnalysisCell, ...]:
        return (
            AnalysisCell(
                f"{prefix}.start",
                period.start.isoformat() if period.start is not None else None,
            ),
            AnalysisCell(
                f"{prefix}.end",
                period.end.isoformat() if period.end is not None else None,
            ),
        )

    @staticmethod
    def _dimension_for_grain(grain: TimeGrain) -> SalesDimension:
        mapping = {
            TimeGrain.DAY: SalesDimension.DAY,
            TimeGrain.WEEK: SalesDimension.WEEK,
            TimeGrain.MONTH: SalesDimension.MONTH,
            TimeGrain.QUARTER: SalesDimension.QUARTER,
            TimeGrain.YEAR: SalesDimension.YEAR,
        }
        return mapping[grain]

    @staticmethod
    def _z_score(confidence: Decimal) -> Decimal:
        if confidence >= Decimal("0.99"):
            return Decimal("2.576")
        if confidence >= Decimal("0.95"):
            return Decimal("1.960")
        if confidence >= Decimal("0.90"):
            return Decimal("1.645")
        return Decimal("1.282")

    @staticmethod
    def _advance_bucket(value: str, grain: TimeGrain, step: int) -> str:
        if grain is TimeGrain.YEAR:
            return str(int(value) + step)
        if grain is TimeGrain.QUARTER:
            year_text, quarter_text = value.split("-Q", maxsplit=1)
            ordinal = int(year_text) * 4 + int(quarter_text) - 1 + step
            return f"{ordinal // 4}-Q{ordinal % 4 + 1}"
        if grain is TimeGrain.MONTH:
            year_text, month_text = value.split("-", maxsplit=1)
            ordinal = int(year_text) * 12 + int(month_text) - 1 + step
            return f"{ordinal // 12}-{ordinal % 12 + 1:02d}"
        if grain is TimeGrain.WEEK:
            year_text, week_text = value.split("-W", maxsplit=1)
            reference = date.fromisocalendar(int(year_text), max(1, int(week_text)), 1)
            advanced = reference + timedelta(weeks=step)
            iso_year, iso_week, _ = advanced.isocalendar()
            return f"{iso_year}-W{iso_week:02d}"
        reference = datetime.fromisoformat(value).date()
        return (reference + timedelta(days=step)).isoformat()

    def _apply_windows(
        self,
        rows: tuple[AnalysisRow, ...],
        windows: tuple[WindowSpec, ...],
    ) -> tuple[AnalysisRow, ...]:
        current = list(rows)
        ordered_windows = tuple(
            window for window in windows if window.kind is not WindowKind.RANK
        ) + tuple(window for window in windows if window.kind is WindowKind.RANK)
        for window in ordered_windows:
            grouped: dict[tuple[str, ...], list[int]] = defaultdict(list)
            for index, row in enumerate(current):
                dimension_map = {cell.name: cell.value for cell in row.dimensions}
                key = tuple(str(dimension_map.get(item.value)) for item in window.partition_by)
                grouped[key].append(index)
            additions: dict[int, AnalysisCell] = {}
            for indexes in grouped.values():
                values = [self._numeric_metric(current[index], window.metric) for index in indexes]
                if window.kind is WindowKind.SHARE_OF_TOTAL:
                    total = sum(values, Decimal("0"))
                    for index, value in zip(indexes, values, strict=True):
                        share = None if total == 0 else (value / total * 100).quantize(PERCENT)
                        additions[index] = AnalysisCell(
                            f"{window.metric.value}.share_of_total", share
                        )
                elif window.kind is WindowKind.RANK:
                    ranked = sorted(set(values), reverse=True)
                    positions = {value: position + 1 for position, value in enumerate(ranked)}
                    for index, value in zip(indexes, values, strict=True):
                        additions[index] = AnalysisCell(
                            f"{window.metric.value}.rank", positions[value]
                        )
                elif window.kind is WindowKind.CUMULATIVE:
                    running = Decimal("0")
                    for index, value in zip(indexes, values, strict=True):
                        running += value
                        additions[index] = AnalysisCell(
                            f"{window.metric.value}.cumulative", running
                        )
                else:
                    size = cast(int, window.size)
                    for position, index in enumerate(indexes):
                        sample = values[max(0, position - size + 1) : position + 1]
                        average = sum(sample, Decimal("0")) / len(sample)
                        additions[index] = AnalysisCell(
                            f"{window.metric.value}.moving_average_{size}",
                            average.quantize(MONEY),
                        )
            current = [
                AnalysisRow(
                    dimensions=row.dimensions,
                    metrics=(*row.metrics, additions[index]),
                )
                for index, row in enumerate(current)
            ]
            if window.kind is WindowKind.RANK and window.top_n is not None:
                rank_name = f"{window.metric.value}.rank"
                current = [
                    row
                    for row in current
                    if isinstance(row.get_metric(rank_name), int)
                    and cast(int, row.get_metric(rank_name)) <= window.top_n
                ]
        return tuple(current)
