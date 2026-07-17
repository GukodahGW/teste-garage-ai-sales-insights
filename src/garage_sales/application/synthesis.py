from calendar import monthrange
from datetime import datetime
from decimal import Decimal
from typing import assert_never

from garage_sales.application.models import (
    CalculateSalesMetric,
    FindTopProducts,
    RepositoryQueryResult,
    SalesMetricValue,
    SalesQueryEvidence,
    TopProduct,
)
from garage_sales.domain.analytics import (
    AggregateSales,
    AnalysisCell,
    AnalysisDataset,
    AnalysisStatus,
    AnomalyAnalysis,
    BasketAnalysis,
    CohortAnalysis,
    CompareSales,
    ForecastSales,
    SalesAnalysisQuery,
    SalesMetric,
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


class DeterministicSalesInsightSynthesizer:
    """Render already-computed evidence without asking a model to calculate or copy values."""

    def synthesize(self, *, question: str, evidence: SalesQueryEvidence) -> str:
        del question
        if not evidence.results:
            return (
                "Não consigo responder com segurança. As perguntas suportadas são total "
                "vendido, número de vendas, unidades vendidas, ticket médio e produtos "
                "mais vendidos, sempre para um único período."
            )

        rendered = tuple(self._render_result(result) for result in evidence.results)
        return "\n".join(rendered)

    def _render_result(self, result: RepositoryQueryResult) -> str:
        query = result.query
        if isinstance(query, CalculateSalesMetric):
            if len(result.records) != 1 or not isinstance(result.records[0], SalesMetricValue):
                raise RuntimeError("evidencia invalida para calculo de vendas")
            return self._render_metric(query, result.records[0])
        if isinstance(query, FindTopProducts):
            products = tuple(record for record in result.records if isinstance(record, TopProduct))
            if len(products) != len(result.records):
                raise RuntimeError("evidencia invalida para ranking de produtos")
            return self._render_top_products(query, products)
        if isinstance(
            query,
            (
                AggregateSales,
                CompareSales,
                BasketAnalysis,
                CohortAnalysis,
                ForecastSales,
                AnomalyAnalysis,
            ),
        ):
            if len(result.records) != 1 or not isinstance(result.records[0], AnalysisDataset):
                raise RuntimeError("evidencia invalida para analise avancada")
            return self._render_analysis(query, result.records[0])
        assert_never(query)

    @staticmethod
    def _render_analysis(query: SalesAnalysisQuery, dataset: AnalysisDataset) -> str:
        if dataset.status is AnalysisStatus.UNSUPPORTED:
            detail = dataset.warnings[0] if dataset.warnings else "semantica nao suportada"
            return f"Não foi possível responder com segurança: {detail}"
        if dataset.status is AnalysisStatus.AMBIGUOUS:
            detail = dataset.warnings[0] if dataset.warnings else "entidade ambígua"
            return f"A pergunta precisa de esclarecimento: {detail}"
        if not dataset.rows:
            if isinstance(query, AnomalyAnalysis):
                return "Nenhuma anomalia foi encontrada no período analisado."
            return "Não foram encontrados dados para a análise solicitada."

        row_texts: list[str] = []
        for row in dataset.rows:
            dimensions = ", ".join(
                f"{_humanize(cell.name)}={cell.value}" for cell in row.dimensions
            )
            metrics = ", ".join(_render_cell(cell) for cell in row.metrics)
            row_texts.append(f"{dimensions}: {metrics}" if dimensions else metrics)

        prefix = "Resultado"
        if isinstance(query, CompareSales):
            prefix = "Comparação"
        elif isinstance(query, BasketAnalysis):
            prefix = "Associação de produtos"
        elif isinstance(query, CohortAnalysis):
            prefix = "Análise de coorte"
        elif isinstance(query, ForecastSales):
            prefix = "Previsão estatística"
        elif isinstance(query, AnomalyAnalysis):
            prefix = "Anomalias encontradas"
        return f"{prefix}: " + "; ".join(row_texts) + "."

    @staticmethod
    def _render_metric(query: CalculateSalesMetric, result: SalesMetricValue) -> str:
        period = _period_phrase(query.sold_from, query.sold_until)
        if result.matched_sales == 0:
            return f"Não foram encontradas vendas {period}."

        if query.metric is SalesMetric.REVENUE:
            assert isinstance(result.value, Decimal)
            return f"O total de vendas {period} foi de R$ {_format_money(result.value)}."
        if query.metric is SalesMetric.SALE_COUNT:
            assert isinstance(result.value, int)
            return f"O número de vendas {period} foi de {_format_integer(result.value)}."
        if query.metric is SalesMetric.UNITS_SOLD:
            assert isinstance(result.value, int)
            return (
                f"A quantidade de unidades vendidas {period} foi de "
                f"{_format_integer(result.value)}."
            )
        if query.metric is SalesMetric.AVERAGE_TICKET:
            assert isinstance(result.value, Decimal)
            return f"O ticket médio {period} foi de R$ {_format_money(result.value)}."
        raise ValueError(f"metrica legada nao suportada: {query.metric.value}")

    @staticmethod
    def _render_top_products(
        query: FindTopProducts,
        products: tuple[TopProduct, ...],
    ) -> str:
        period = _period_phrase(query.sold_from, query.sold_until)
        if not products:
            return f"Não foram encontrados produtos vendidos {period}."
        if len(products) == 1:
            product = products[0]
            unit_label = "unidade" if product.quantity_sold == 1 else "unidades"
            return (
                f"O produto mais vendido {period} foi {product.name}, com "
                f"{_format_integer(product.quantity_sold)} {unit_label}."
            )

        ranking = "; ".join(
            f"{product.name} ({_format_integer(product.quantity_sold)} unidades)"
            for product in products
        )
        return f"Os produtos mais vendidos {period} foram: {ranking}."


def _period_phrase(sold_from: datetime | None, sold_until: datetime | None) -> str:
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


def _format_integer(value: int) -> str:
    return f"{value:,}".replace(",", ".")


_LABELS = {
    "product": "produto",
    "product_a": "produto A",
    "product_b": "produto B",
    "category": "categoria",
    "customer": "cliente",
    "month": "mês",
    "quarter": "trimestre",
    "year": "ano",
    "currency": "moeda",
    "revenue": "receita",
    "gross_revenue": "receita bruta",
    "net_revenue": "receita líquida",
    "order_count": "pedidos",
    "sale_count": "vendas",
    "units_sold": "unidades",
    "average_ticket": "ticket médio",
    "distinct_customers": "clientes distintos",
    "refund_amount": "estornos",
    "current": "atual",
    "baseline": "base",
    "absolute_change": "diferença",
    "percentage_change": "variação",
}


def _humanize(name: str) -> str:
    return " ".join(_LABELS.get(part, part.replace("_", " ")) for part in name.split("."))


def _render_cell(cell: AnalysisCell) -> str:
    label = _humanize(cell.name)
    value = cell.value
    if value is None:
        return f"{label}=indefinido"
    if isinstance(value, bool):
        return f"{label}={'sim' if value else 'não'}"
    if isinstance(value, int):
        return f"{label}={_format_integer(value)}"
    if isinstance(value, Decimal):
        percent_names = ("percentage", "share", "retention")
        ratio_names = ("support", "confidence")
        if any(item in cell.name for item in percent_names):
            return f"{label}={_format_money(value)}%"
        if any(item in cell.name for item in ratio_names):
            return f"{label}={_format_money(value * 100)}%"
        monetary_names = ("revenue", "ticket", "refund", "forecast", "bound")
        if any(item in cell.name for item in monetary_names):
            return f"{label}=R$ {_format_money(value)}"
        return f"{label}={_format_money(value)}"
    return f"{label}={value}"
