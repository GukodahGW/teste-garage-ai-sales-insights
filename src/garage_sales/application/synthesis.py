from calendar import monthrange
from decimal import Decimal
from typing import assert_never

from garage_sales.application.models import RepositoryQueryResult, SalesQueryEvidence
from garage_sales.domain.analytics import (
    AggregateSales,
    AnalysisRow,
    CompareSales,
    SalesAnalysisResult,
    SalesDimension,
    SalesMetric,
    SortDirection,
    TimePeriod,
)

_MONTH_NAMES = (
    "",
    "janeiro",
    "fevereiro",
    "março",
    "abril",
    "maio",
    "junho",
    "julho",
    "agosto",
    "setembro",
    "outubro",
    "novembro",
    "dezembro",
)

_DIMENSION_LABELS = {
    SalesDimension.PRODUCT: "produto",
    SalesDimension.CATEGORY: "categoria",
    SalesDimension.CUSTOMER: "cliente",
    SalesDimension.DAY: "dia",
    SalesDimension.WEEK: "semana",
    SalesDimension.MONTH: "mês",
    SalesDimension.YEAR: "ano",
}

_DIMENSION_ARTICLES = {
    SalesDimension.CATEGORY: "A",
    SalesDimension.WEEK: "A",
}

_METRIC_LABELS = {
    SalesMetric.REVENUE: "receita",
    SalesMetric.SALE_COUNT: "número de vendas",
    SalesMetric.UNITS_SOLD: "unidades vendidas",
    SalesMetric.AVERAGE_TICKET: "ticket médio",
}


class DeterministicSalesInsightSynthesizer:
    """Render database-computed evidence without asking a model to calculate values."""

    def synthesize(self, *, question: str, evidence: SalesQueryEvidence) -> str:
        del question
        if not evidence.results:
            return (
                "Não consigo responder com segurança. Posso calcular totais, agrupamentos, "
                "rankings e comparações de vendas por período, produto, categoria ou cliente."
            )
        return self._render_result(evidence.results[0])

    def _render_result(self, result: RepositoryQueryResult) -> str:
        if len(result.records) != 1 or not isinstance(result.records[0], SalesAnalysisResult):
            raise RuntimeError("evidencia invalida para analise de vendas")
        query = result.query
        dataset = result.records[0]
        if isinstance(query, AggregateSales):
            return self._render_aggregate(query, dataset)
        if isinstance(query, CompareSales):
            return self._render_compare(query, dataset)
        assert_never(query)

    @staticmethod
    def _render_aggregate(query: AggregateSales, result: SalesAnalysisResult) -> str:
        period = _period_phrase(query.period)
        if not result.rows:
            return f"Não foram encontradas vendas {period}."

        if not query.dimensions and len(query.metrics) == 1:
            value = result.rows[0].metric_value(query.metrics[0].value)
            return _render_fundamental_metric(query.metrics[0], value, period)

        if (
            len(result.rows) == 1
            and len(query.dimensions) == 1
            and len(query.metrics) == 1
            and query.limit == 1
            and query.sort
        ):
            dimension = query.dimensions[0]
            metric = query.metrics[0]
            direction = query.sort[0].direction
            qualifier = "maior" if direction is SortDirection.DESCENDING else "menor"
            article = _DIMENSION_ARTICLES.get(dimension, "O")
            dimension_value = result.rows[0].dimensions[0].value
            metric_value = result.rows[0].metric_value(metric.value)
            return (
                f"{article} {_DIMENSION_LABELS[dimension]} com {qualifier} "
                f"{_METRIC_LABELS[metric]} {period} foi {dimension_value}, com "
                f"{_render_metric_value(metric, metric_value)}."
            )

        if (
            query.dimensions == (SalesDimension.PRODUCT,)
            and query.metrics == (SalesMetric.UNITS_SOLD,)
            and query.sort
            and query.sort[0].direction is SortDirection.DESCENDING
        ):
            ranking = "; ".join(
                f"{row.dimensions[0].value} "
                f"({_render_metric_value(SalesMetric.UNITS_SOLD, row.metric_value('units_sold'))})"
                for row in result.rows
            )
            return f"Os produtos mais vendidos {period} foram: {ranking}."

        return "Resultado: " + "; ".join(_render_row(row) for row in result.rows) + "."

    @staticmethod
    def _render_compare(query: CompareSales, result: SalesAnalysisResult) -> str:
        if not result.rows:
            return "Não foram encontradas vendas nos períodos comparados."
        rows = "; ".join(_render_comparison_row(row, query.metrics) for row in result.rows)
        return f"Comparação: {rows}."


def _render_fundamental_metric(metric: SalesMetric, value: object, period: str) -> str:
    rendered = _render_metric_value(metric, value)
    if metric is SalesMetric.REVENUE:
        return f"O total de vendas {period} foi de {rendered}."
    if metric is SalesMetric.SALE_COUNT:
        return f"O número de vendas {period} foi de {rendered}."
    if metric is SalesMetric.UNITS_SOLD:
        return f"A quantidade de unidades vendidas {period} foi de {rendered}."
    if metric is SalesMetric.AVERAGE_TICKET:
        return f"O ticket médio {period} foi de {rendered}."
    raise ValueError(f"metrica nao suportada: {metric.value}")


def _render_row(row: AnalysisRow) -> str:
    dimensions = ", ".join(
        f"{_DIMENSION_LABELS[SalesDimension(cell.name)]}={cell.value}"
        for cell in row.dimensions
    )
    metrics = ", ".join(
        f"{_METRIC_LABELS[SalesMetric(cell.name)]}="
        f"{_render_metric_value(SalesMetric(cell.name), cell.value)}"
        for cell in row.metrics
    )
    return f"{dimensions}: {metrics}" if dimensions else metrics


def _render_comparison_row(row: AnalysisRow, metrics: tuple[SalesMetric, ...]) -> str:
    dimensions = ", ".join(
        f"{_DIMENSION_LABELS[SalesDimension(cell.name)]}={cell.value}"
        for cell in row.dimensions
    )
    values: list[str] = []
    for metric in metrics:
        current = row.metric_value(f"{metric.value}.current")
        baseline = row.metric_value(f"{metric.value}.baseline")
        absolute = row.metric_value(f"{metric.value}.absolute_change")
        percentage = row.metric_value(f"{metric.value}.percentage_change")
        percentage_text = (
            "indefinida"
            if percentage is None
            else f"{_format_decimal(Decimal(str(percentage)))}%"
        )
        values.append(
            f"{_METRIC_LABELS[metric]} atual={_render_metric_value(metric, current)}, "
            f"base={_render_metric_value(metric, baseline)}, "
            f"diferença={_render_metric_value(metric, absolute)}, "
            f"variação={percentage_text}"
        )
    rendered_values = ", ".join(values)
    return f"{dimensions}: {rendered_values}" if dimensions else rendered_values


def _render_metric_value(metric: SalesMetric, value: object) -> str:
    if value is None:
        return "indefinido"
    if metric in {SalesMetric.REVENUE, SalesMetric.AVERAGE_TICKET}:
        return f"R$ {_format_money(Decimal(str(value)))}"
    return _format_integer(int(str(value)))


def _period_phrase(period: TimePeriod) -> str:
    sold_from = period.start
    sold_until = period.end
    if sold_from is None and sold_until is None:
        return "no período disponível"
    if sold_from is not None and sold_until is not None:
        if (
            sold_from.year == sold_until.year
            and sold_from.month == 1
            and sold_from.day == 1
            and sold_until.month == 12
            and sold_until.day == 31
        ):
            return f"em {sold_from.year}"
        if (
            sold_from.year == sold_until.year
            and sold_from.month == sold_until.month
            and sold_from.day == 1
            and sold_until.day == monthrange(sold_until.year, sold_until.month)[1]
        ):
            return f"em {_MONTH_NAMES[sold_from.month]} de {sold_from.year}"
        return f"entre {sold_from:%d/%m/%Y} e {sold_until:%d/%m/%Y}"
    if sold_from is not None:
        return f"a partir de {sold_from:%d/%m/%Y}"
    assert sold_until is not None
    return f"até {sold_until:%d/%m/%Y}"


def _format_money(value: Decimal) -> str:
    formatted = f"{value:,.2f}"
    return formatted.replace(",", "_").replace(".", ",").replace("_", ".")


def _format_decimal(value: Decimal) -> str:
    formatted = f"{value:.4f}".rstrip("0").rstrip(".")
    return formatted.replace(".", ",")


def _format_integer(value: int) -> str:
    return f"{value:,}".replace(",", ".")
