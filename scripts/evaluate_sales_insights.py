"""Measure the empirical accuracy of the nondeterministic sales query planner.

The oracle intentionally reads raw relational rows and computes the expected facts in
Python.  It does not call the production planner, analytics repository, or synthesizer.
All expectations are prepared before the first HTTP request is made.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import time
import unicodedata
from collections.abc import Callable, Iterable, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from statistics import mean
from typing import Literal, TypeAlias
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from sqlalchemy import create_engine, select
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session

from garage_sales.config import RelationalDatabaseSettings, load_runtime_env
from garage_sales.infrastructure.sqlalchemy.models import (
    CustomerModel,
    ProductModel,
    SaleModel,
)

MetricName: TypeAlias = Literal[
    "revenue",
    "sale_count",
    "units_sold",
    "average_ticket",
]
DimensionName: TypeAlias = Literal[
    "product",
    "category",
    "customer",
    "day",
    "week",
    "month",
    "year",
]
FilterField: TypeAlias = Literal["product", "category", "customer"]
FilterOperator: TypeAlias = Literal["equals", "contains", "in"]
SortDirection: TypeAlias = Literal["asc", "desc"]
ComparisonValue: TypeAlias = Literal[
    "current",
    "baseline",
    "absolute_change",
    "percentage_change",
]
MetricValue: TypeAlias = Decimal | int

MONEY_QUANTUM = Decimal("0.01")
PERCENT_QUANTUM = Decimal("0.0001")
DEFAULT_API_URL = "http://127.0.0.1:8000"


@dataclass(frozen=True, slots=True)
class Period:
    start: datetime
    end: datetime

    def contains(self, value: datetime) -> bool:
        normalized = _as_utc(value)
        return self.start <= normalized <= self.end


@dataclass(frozen=True, slots=True)
class OracleFilter:
    field: FilterField
    values: tuple[str, ...]
    operator: FilterOperator = "equals"


@dataclass(frozen=True, slots=True)
class OracleSort:
    metric: MetricName
    direction: SortDirection = "desc"
    comparison: ComparisonValue | None = None


@dataclass(frozen=True, slots=True)
class AggregateOracle:
    metrics: tuple[MetricName, ...]
    period: Period
    dimensions: tuple[DimensionName, ...] = ()
    filters: tuple[OracleFilter, ...] = ()
    sort: OracleSort | None = None
    limit: int | None = None


@dataclass(frozen=True, slots=True)
class CompareOracle:
    metrics: tuple[MetricName, ...]
    current_period: Period
    baseline_period: Period
    dimensions: tuple[DimensionName, ...] = ()
    filters: tuple[OracleFilter, ...] = ()
    sort: OracleSort | None = None
    limit: int | None = None


OracleQuery: TypeAlias = AggregateOracle | CompareOracle


@dataclass(frozen=True, slots=True)
class EvaluationCase:
    name: str
    question: str
    query: OracleQuery
    capability: str


@dataclass(frozen=True, slots=True)
class OracleSale:
    sold_at: datetime
    total_amount: Decimal
    quantity: int
    product: str
    product_sku: str
    category: str
    customer: str
    customer_email: str


@dataclass(frozen=True, slots=True)
class RequiredFact:
    """Values that must occur together in one answer segment."""

    context: tuple[str, ...]
    values: tuple[str, ...]

    def describe(self) -> str:
        context = " + ".join(self.context) if self.context else "resposta"
        return f"{context} -> {', '.join(self.values)}"


@dataclass(frozen=True, slots=True)
class PreparedCase:
    case: EvaluationCase
    required_facts: tuple[RequiredFact, ...]


@dataclass(frozen=True, slots=True)
class HttpObservation:
    status: int | None
    answer: str | None
    error: str | None = None
    plan: dict[str, object] | None = None


@dataclass(frozen=True, slots=True)
class EvaluationAttempt:
    case: str
    capability: str
    question: str
    trial: int
    passed: bool
    status: int | None
    duration_seconds: float
    answer: str | None
    missing_facts: tuple[str, ...]
    error: str | None
    plan: dict[str, object] | None


@dataclass(frozen=True, slots=True)
class CapabilitySummary:
    capability: str
    attempts: int
    passed: int
    pass_rate: float


@dataclass(frozen=True, slots=True)
class EvaluationSummary:
    attempts: int
    passed: int
    pass_rate: float
    confidence_95_low: float
    confidence_95_high: float
    mean_latency_seconds: float
    p95_latency_seconds: float
    capabilities: tuple[CapabilitySummary, ...]


@dataclass(frozen=True, slots=True)
class _AggregateRow:
    dimensions: tuple[str, ...]
    metrics: tuple[tuple[MetricName, MetricValue], ...]

    def metric(self, name: MetricName) -> MetricValue:
        return dict(self.metrics)[name]


@dataclass(frozen=True, slots=True)
class _ComparisonMetric:
    name: MetricName
    current: MetricValue
    baseline: MetricValue
    absolute_change: MetricValue
    percentage_change: Decimal | None


@dataclass(frozen=True, slots=True)
class _ComparisonRow:
    dimensions: tuple[str, ...]
    metrics: tuple[_ComparisonMetric, ...]

    def metric(self, name: MetricName) -> _ComparisonMetric:
        return next(metric for metric in self.metrics if metric.name == name)


def _year(year: int) -> Period:
    return Period(
        datetime(year, 1, 1, tzinfo=UTC),
        datetime(year, 12, 31, 23, 59, 59, 999999, tzinfo=UTC),
    )


def _month(year: int, month: int) -> Period:
    following = (
        datetime(year + 1, 1, 1, tzinfo=UTC)
        if month == 12
        else datetime(year, month + 1, 1, tzinfo=UTC)
    )
    return Period(
        datetime(year, month, 1, tzinfo=UTC),
        following - timedelta(microseconds=1),
    )


YEAR_2025 = _year(2025)
JANUARY_2025 = _month(2025, 1)
FEBRUARY_2025 = _month(2025, 2)
FIRST_QUARTER_2025 = Period(
    datetime(2025, 1, 1, tzinfo=UTC),
    datetime(2025, 3, 31, 23, 59, 59, 999999, tzinfo=UTC),
)
FIRST_HALF_FEBRUARY_2025 = Period(
    datetime(2025, 2, 1, tzinfo=UTC),
    datetime(2025, 2, 15, 23, 59, 59, 999999, tzinfo=UTC),
)
SECOND_HALF_FEBRUARY_2025 = Period(
    datetime(2025, 2, 16, tzinfo=UTC),
    datetime(2025, 2, 28, 23, 59, 59, 999999, tzinfo=UTC),
)


DEFAULT_CASES: tuple[EvaluationCase, ...] = (
    EvaluationCase(
        name="annual_revenue",
        capability="total",
        question="Qual foi o total de vendas em 2025?",
        query=AggregateOracle(("revenue",), YEAR_2025),
    ),
    EvaluationCase(
        name="monthly_sale_count",
        capability="total",
        question="Quantas vendas foram realizadas em fevereiro de 2025?",
        query=AggregateOracle(("sale_count",), FEBRUARY_2025),
    ),
    EvaluationCase(
        name="monthly_average_ticket",
        capability="average",
        question="Qual foi o ticket médio em janeiro de 2025?",
        query=AggregateOracle(("average_ticket",), JANUARY_2025),
    ),
    EvaluationCase(
        name="best_week_by_revenue",
        capability="ranking",
        question="Qual foi a semana de 2025 que mais vendeu?",
        query=AggregateOracle(
            ("revenue",),
            YEAR_2025,
            dimensions=("week",),
            sort=OracleSort("revenue", "desc"),
            limit=1,
        ),
    ),
    EvaluationCase(
        name="top_five_products_by_units",
        capability="ranking",
        question="Quais foram os cinco produtos mais vendidos em unidades em 2025?",
        query=AggregateOracle(
            ("units_sold",),
            YEAR_2025,
            dimensions=("product",),
            sort=OracleSort("units_sold", "desc"),
            limit=5,
        ),
    ),
    EvaluationCase(
        name="monthly_revenue_series",
        capability="grouping",
        question="Mostre a receita de cada mês de 2025.",
        query=AggregateOracle(("revenue",), YEAR_2025, dimensions=("month",)),
    ),
    EvaluationCase(
        name="category_revenue_and_units",
        capability="multiple_metrics",
        question="Mostre a receita e as unidades vendidas por categoria em 2025.",
        query=AggregateOracle(
            ("revenue", "units_sold"),
            YEAR_2025,
            dimensions=("category",),
        ),
    ),
    EvaluationCase(
        name="top_customer_by_revenue",
        capability="ranking",
        question="Qual cliente gerou a maior receita em 2025?",
        query=AggregateOracle(
            ("revenue",),
            YEAR_2025,
            dimensions=("customer",),
            sort=OracleSort("revenue", "desc"),
            limit=1,
        ),
    ),
    EvaluationCase(
        name="filtered_product_multiple_metrics",
        capability="filter",
        question=(
            "Qual foi a receita e quantas unidades do Product E foram vendidas em 2025?"
        ),
        query=AggregateOracle(
            ("revenue", "units_sold"),
            YEAR_2025,
            filters=(OracleFilter("product", ("Product E",)),),
        ),
    ),
    EvaluationCase(
        name="filtered_category_product_ranking",
        capability="filter_and_ranking",
        question=(
            "Liste os produtos da Category 1 por receita, do maior para o menor, em 2025."
        ),
        query=AggregateOracle(
            ("revenue",),
            YEAR_2025,
            dimensions=("product",),
            filters=(OracleFilter("category", ("Category 1",)),),
            sort=OracleSort("revenue", "desc"),
        ),
    ),
    EvaluationCase(
        name="month_over_month_revenue",
        capability="comparison",
        question="Compare a receita de fevereiro de 2025 com janeiro de 2025.",
        query=CompareOracle(("revenue",), FEBRUARY_2025, JANUARY_2025),
    ),
    EvaluationCase(
        name="month_over_month_by_category",
        capability="comparison_multiple_metrics",
        question=(
            "Compare receita e unidades vendidas por categoria em fevereiro de 2025 "
            "contra janeiro de 2025."
        ),
        query=CompareOracle(
            ("revenue", "units_sold"),
            FEBRUARY_2025,
            JANUARY_2025,
            dimensions=("category",),
        ),
    ),
    EvaluationCase(
        name="lowest_revenue_day",
        capability="ascending_ranking",
        question="Qual foi o dia de 2025 com a menor receita?",
        query=AggregateOracle(
            ("revenue",),
            YEAR_2025,
            dimensions=("day",),
            sort=OracleSort("revenue", "asc"),
            limit=1,
        ),
    ),
    EvaluationCase(
        name="monthly_category_revenue",
        capability="two_dimensions",
        question="Detalhe a receita por mês e por categoria em 2025.",
        query=AggregateOracle(
            ("revenue",),
            YEAR_2025,
            dimensions=("month", "category"),
        ),
    ),
    EvaluationCase(
        name="annual_all_metrics",
        capability="multiple_metrics",
        question=(
            "Em 2025, informe a receita total, o número de vendas, as unidades vendidas "
            "e o ticket médio."
        ),
        query=AggregateOracle(
            ("revenue", "sale_count", "units_sold", "average_ticket"),
            YEAR_2025,
        ),
    ),
    EvaluationCase(
        name="january_units_sold",
        capability="total",
        question="Quantas unidades foram vendidas em janeiro de 2025?",
        query=AggregateOracle(("units_sold",), JANUARY_2025),
    ),
    EvaluationCase(
        name="first_quarter_revenue_and_sales",
        capability="custom_period_multiple_metrics",
        question=(
            "Qual foi a receita e o número de vendas no primeiro trimestre de 2025, "
            "de 1º de janeiro até 31 de março?"
        ),
        query=AggregateOracle(
            ("revenue", "sale_count"),
            FIRST_QUARTER_2025,
        ),
    ),
    EvaluationCase(
        name="filtered_category_average_ticket",
        capability="filter",
        question="Qual foi o ticket médio da Category 2 em fevereiro de 2025?",
        query=AggregateOracle(
            ("average_ticket",),
            FEBRUARY_2025,
            filters=(OracleFilter("category", ("Category 2",)),),
        ),
    ),
    EvaluationCase(
        name="filtered_product_three_metrics",
        capability="filter_multiple_metrics",
        question=(
            "Em 2025, qual foi a receita, o número de vendas e as unidades vendidas "
            "do Product A?"
        ),
        query=AggregateOracle(
            ("revenue", "sale_count", "units_sold"),
            YEAR_2025,
            filters=(OracleFilter("product", ("Product A",)),),
        ),
    ),
    EvaluationCase(
        name="filtered_customer_revenue_and_ticket",
        capability="filter_multiple_metrics",
        question="Qual foi a receita e o ticket médio de Alice Brown em 2025?",
        query=AggregateOracle(
            ("revenue", "average_ticket"),
            YEAR_2025,
            filters=(OracleFilter("customer", ("Alice Brown",)),),
        ),
    ),
    EvaluationCase(
        name="top_three_products_by_revenue",
        capability="ranking",
        question="Quais foram os três produtos com maior receita em 2025?",
        query=AggregateOracle(
            ("revenue",),
            YEAR_2025,
            dimensions=("product",),
            sort=OracleSort("revenue", "desc"),
            limit=3,
        ),
    ),
    EvaluationCase(
        name="bottom_two_products_by_revenue",
        capability="ascending_ranking",
        question="Quais foram os dois produtos com menor receita em 2025?",
        query=AggregateOracle(
            ("revenue",),
            YEAR_2025,
            dimensions=("product",),
            sort=OracleSort("revenue", "asc"),
            limit=2,
        ),
    ),
    EvaluationCase(
        name="top_three_customers_by_units",
        capability="ranking",
        question="Quais foram os três clientes que compraram mais unidades em 2025?",
        query=AggregateOracle(
            ("units_sold",),
            YEAR_2025,
            dimensions=("customer",),
            sort=OracleSort("units_sold", "desc"),
            limit=3,
        ),
    ),
    EvaluationCase(
        name="category_highest_average_ticket",
        capability="ranking",
        question="Qual categoria teve o maior ticket médio em 2025?",
        query=AggregateOracle(
            ("average_ticket",),
            YEAR_2025,
            dimensions=("category",),
            sort=OracleSort("average_ticket", "desc"),
            limit=1,
        ),
    ),
    EvaluationCase(
        name="category_fewest_sales",
        capability="ascending_ranking",
        question="Qual categoria teve o menor número de vendas em 2025?",
        query=AggregateOracle(
            ("sale_count",),
            YEAR_2025,
            dimensions=("category",),
            sort=OracleSort("sale_count", "asc"),
            limit=1,
        ),
    ),
    EvaluationCase(
        name="top_five_days_by_units",
        capability="temporal_ranking",
        question="Quais foram os cinco dias de 2025 com mais unidades vendidas?",
        query=AggregateOracle(
            ("units_sold",),
            YEAR_2025,
            dimensions=("day",),
            sort=OracleSort("units_sold", "desc"),
            limit=5,
        ),
    ),
    EvaluationCase(
        name="weekly_sale_count_series",
        capability="temporal_grouping",
        question="Mostre o número de vendas de cada semana de 2025.",
        query=AggregateOracle(
            ("sale_count",),
            YEAR_2025,
            dimensions=("week",),
        ),
    ),
    EvaluationCase(
        name="product_revenue_and_average_ticket",
        capability="grouping_multiple_metrics",
        question="Mostre a receita e o ticket médio por produto em 2025.",
        query=AggregateOracle(
            ("revenue", "average_ticket"),
            YEAR_2025,
            dimensions=("product",),
        ),
    ),
    EvaluationCase(
        name="customer_revenue_sales_and_units",
        capability="grouping_multiple_metrics",
        question=(
            "Detalhe por cliente a receita, o número de vendas e as unidades vendidas "
            "em 2025."
        ),
        query=AggregateOracle(
            ("revenue", "sale_count", "units_sold"),
            YEAR_2025,
            dimensions=("customer",),
        ),
    ),
    EvaluationCase(
        name="category_all_metrics",
        capability="grouping_four_metrics",
        question=(
            "Para cada categoria em 2025, apresente receita, número de vendas, "
            "unidades vendidas e ticket médio."
        ),
        query=AggregateOracle(
            ("revenue", "sale_count", "units_sold", "average_ticket"),
            YEAR_2025,
            dimensions=("category",),
        ),
    ),
    EvaluationCase(
        name="monthly_sales_units_and_ticket",
        capability="temporal_grouping_multiple_metrics",
        question=(
            "Por mês de 2025, mostre o número de vendas, as unidades vendidas "
            "e o ticket médio."
        ),
        query=AggregateOracle(
            ("sale_count", "units_sold", "average_ticket"),
            YEAR_2025,
            dimensions=("month",),
        ),
    ),
    EvaluationCase(
        name="product_category_revenue",
        capability="two_dimensions",
        question="Detalhe a receita de 2025 por produto e categoria.",
        query=AggregateOracle(
            ("revenue",),
            YEAR_2025,
            dimensions=("product", "category"),
        ),
    ),
    EvaluationCase(
        name="top_ten_customer_product_pairs",
        capability="two_dimensions_ranking",
        question=(
            "Quais foram as dez combinações de cliente e produto com maior receita em 2025?"
        ),
        query=AggregateOracle(
            ("revenue",),
            YEAR_2025,
            dimensions=("customer", "product"),
            sort=OracleSort("revenue", "desc"),
            limit=10,
        ),
    ),
    EvaluationCase(
        name="top_eight_month_product_units",
        capability="two_dimensions_ranking",
        question=(
            "Liste as oito combinações de mês e produto com mais unidades vendidas em 2025."
        ),
        query=AggregateOracle(
            ("units_sold",),
            YEAR_2025,
            dimensions=("month", "product"),
            sort=OracleSort("units_sold", "desc"),
            limit=8,
        ),
    ),
    EvaluationCase(
        name="top_ten_week_category_revenue",
        capability="two_dimensions_ranking",
        question=(
            "Liste as dez combinações de semana e categoria com maior receita em 2025."
        ),
        query=AggregateOracle(
            ("revenue",),
            YEAR_2025,
            dimensions=("week", "category"),
            sort=OracleSort("revenue", "desc"),
            limit=10,
        ),
    ),
    EvaluationCase(
        name="category_one_all_metrics",
        capability="filter_four_metrics",
        question=(
            "Para a Category 1 em 2025, informe receita, número de vendas, "
            "unidades vendidas e ticket médio."
        ),
        query=AggregateOracle(
            ("revenue", "sale_count", "units_sold", "average_ticket"),
            YEAR_2025,
            filters=(OracleFilter("category", ("Category 1",)),),
        ),
    ),
    EvaluationCase(
        name="product_name_contains_top_ticket",
        capability="contains_filter_and_ranking",
        question=(
            "Entre os produtos cujo nome contém 'Product', quais são os três com maior "
            "ticket médio em 2025?"
        ),
        query=AggregateOracle(
            ("average_ticket",),
            YEAR_2025,
            dimensions=("product",),
            filters=(OracleFilter("product", ("Product",), "contains"),),
            sort=OracleSort("average_ticket", "desc"),
            limit=3,
        ),
    ),
    EvaluationCase(
        name="selected_customers_revenue",
        capability="in_filter",
        question=(
            "Mostre a receita por cliente em 2025 somente para John Doe e Alice Brown."
        ),
        query=AggregateOracle(
            ("revenue",),
            YEAR_2025,
            dimensions=("customer",),
            filters=(OracleFilter("customer", ("John Doe", "Alice Brown"), "in"),),
        ),
    ),
    EvaluationCase(
        name="selected_products_revenue_and_units",
        capability="in_filter_multiple_metrics",
        question=(
            "Mostre receita e unidades vendidas por produto em 2025 apenas para "
            "Product A, Product C e Product E."
        ),
        query=AggregateOracle(
            ("revenue", "units_sold"),
            YEAR_2025,
            dimensions=("product",),
            filters=(
                OracleFilter(
                    "product",
                    ("Product A", "Product C", "Product E"),
                    "in",
                ),
            ),
        ),
    ),
    EvaluationCase(
        name="customer_email_filter",
        capability="identifier_filter",
        question=(
            "Qual foi a receita e quantas unidades foram vendidas em 2025 para o cliente "
            "de e-mail jane@example.com?"
        ),
        query=AggregateOracle(
            ("revenue", "units_sold"),
            YEAR_2025,
            filters=(OracleFilter("customer", ("jane@example.com",)),),
        ),
    ),
    EvaluationCase(
        name="product_sku_filter",
        capability="identifier_filter",
        question=(
            "Qual foi a receita e quantas unidades do produto SKU005 foram vendidas em 2025?"
        ),
        query=AggregateOracle(
            ("revenue", "units_sold"),
            YEAR_2025,
            filters=(OracleFilter("product", ("SKU005",)),),
        ),
    ),
    EvaluationCase(
        name="category_one_customer_ranking",
        capability="filter_and_ranking",
        question=(
            "Na Category 1, quais clientes geraram mais receita em 2025? "
            "Liste do maior para o menor."
        ),
        query=AggregateOracle(
            ("revenue",),
            YEAR_2025,
            dimensions=("customer",),
            filters=(OracleFilter("category", ("Category 1",)),),
            sort=OracleSort("revenue", "desc"),
        ),
    ),
    EvaluationCase(
        name="product_e_customer_units_ranking",
        capability="filter_and_ranking",
        question=(
            "Para o Product E, ordene os clientes pela quantidade de unidades compradas "
            "em 2025, do maior para o menor."
        ),
        query=AggregateOracle(
            ("units_sold",),
            YEAR_2025,
            dimensions=("customer",),
            filters=(OracleFilter("product", ("Product E",)),),
            sort=OracleSort("units_sold", "desc"),
        ),
    ),
    EvaluationCase(
        name="february_top_three_products_revenue",
        capability="period_filter_and_ranking",
        question="Quais foram os três produtos com maior receita em fevereiro de 2025?",
        query=AggregateOracle(
            ("revenue",),
            FEBRUARY_2025,
            dimensions=("product",),
            sort=OracleSort("revenue", "desc"),
            limit=3,
        ),
    ),
    EvaluationCase(
        name="january_category_ticket_ascending",
        capability="period_ascending_ranking",
        question=(
            "Ordene as categorias pelo ticket médio de janeiro de 2025, "
            "do menor para o maior."
        ),
        query=AggregateOracle(
            ("average_ticket",),
            JANUARY_2025,
            dimensions=("category",),
            sort=OracleSort("average_ticket", "asc"),
        ),
    ),
    EvaluationCase(
        name="month_over_month_all_metrics",
        capability="comparison_four_metrics",
        question=(
            "Compare fevereiro de 2025 com janeiro de 2025 em receita, número de vendas, "
            "unidades vendidas e ticket médio."
        ),
        query=CompareOracle(
            ("revenue", "sale_count", "units_sold", "average_ticket"),
            FEBRUARY_2025,
            JANUARY_2025,
        ),
    ),
    EvaluationCase(
        name="month_over_month_by_product",
        capability="comparison_grouping",
        question=(
            "Compare a receita por produto de fevereiro de 2025 contra janeiro de 2025."
        ),
        query=CompareOracle(
            ("revenue",),
            FEBRUARY_2025,
            JANUARY_2025,
            dimensions=("product",),
        ),
    ),
    EvaluationCase(
        name="month_over_month_by_customer",
        capability="comparison_grouping_multiple_metrics",
        question=(
            "Compare receita e unidades vendidas por cliente em fevereiro de 2025 "
            "contra janeiro de 2025."
        ),
        query=CompareOracle(
            ("revenue", "units_sold"),
            FEBRUARY_2025,
            JANUARY_2025,
            dimensions=("customer",),
        ),
    ),
    EvaluationCase(
        name="category_one_month_over_month",
        capability="filtered_comparison",
        question=(
            "Para a Category 1, compare a receita de fevereiro de 2025 com janeiro de 2025."
        ),
        query=CompareOracle(
            ("revenue",),
            FEBRUARY_2025,
            JANUARY_2025,
            filters=(OracleFilter("category", ("Category 1",)),),
        ),
    ),
    EvaluationCase(
        name="february_halves_by_category",
        capability="custom_period_comparison_grouping",
        question=(
            "Compare a receita por categoria da segunda quinzena de fevereiro de 2025, "
            "dos dias 16 a 28, com a primeira quinzena, dos dias 1 a 15."
        ),
        query=CompareOracle(
            ("revenue",),
            SECOND_HALF_FEBRUARY_2025,
            FIRST_HALF_FEBRUARY_2025,
            dimensions=("category",),
        ),
    ),
)


def load_oracle_sales(database_url: str | URL) -> tuple[OracleSale, ...]:
    """Load the raw facts needed by the independent in-memory oracle."""

    engine = create_engine(database_url, pool_pre_ping=True)
    statement = (
        select(
            SaleModel.sold_at,
            SaleModel.total_amount,
            SaleModel.quantity,
            ProductModel.name,
            ProductModel.sku,
            ProductModel.category,
            CustomerModel.name,
            CustomerModel.email,
        )
        .select_from(SaleModel)
        .outerjoin(ProductModel, ProductModel.id == SaleModel.product_id)
        .outerjoin(CustomerModel, CustomerModel.id == SaleModel.customer_id)
        .order_by(SaleModel.id)
    )
    try:
        with Session(engine) as session:
            raw_rows = tuple(session.execute(statement))
    finally:
        engine.dispose()

    return tuple(
        OracleSale(
            sold_at=_as_utc(row[0]),
            total_amount=Decimal(str(row[1])).quantize(MONEY_QUANTUM),
            quantity=int(row[2]),
            product=str(row[3]) if row[3] is not None else "Produto desconhecido",
            product_sku=str(row[4]) if row[4] is not None else "",
            category=str(row[5]) if row[5] is not None else "Sem categoria",
            customer=str(row[6]) if row[6] is not None else "Cliente não identificado",
            customer_email=str(row[7]) if row[7] is not None else "",
        )
        for row in raw_rows
    )


def prepare_cases(
    cases: Sequence[EvaluationCase],
    sales: Sequence[OracleSale],
) -> tuple[PreparedCase, ...]:
    """Compute every deterministic expectation before any model-backed request."""

    return tuple(
        PreparedCase(case=case, required_facts=_required_facts(case.query, sales))
        for case in cases
    )


def evaluate_batch(
    prepared_cases: Sequence[PreparedCase],
    ask: Callable[[str], HttpObservation],
    *,
    trials: int,
    progress: Callable[[EvaluationAttempt], None] | None = None,
) -> tuple[EvaluationAttempt, ...]:
    if trials < 1:
        raise ValueError("trials deve ser positivo")

    attempts: list[EvaluationAttempt] = []
    for prepared in prepared_cases:
        for trial in range(1, trials + 1):
            started = time.perf_counter()
            try:
                observation = ask(prepared.case.question)
            except Exception as error:  # keep the statistical run alive after one failure
                observation = HttpObservation(
                    status=None,
                    answer=None,
                    error=f"{type(error).__name__}: {error}",
                )
            duration = time.perf_counter() - started
            missing = missing_facts(observation.answer or "", prepared.required_facts)
            passed = (
                observation.status is not None
                and 200 <= observation.status < 300
                and observation.answer is not None
                and not missing
                and observation.error is None
            )
            attempt = EvaluationAttempt(
                case=prepared.case.name,
                capability=prepared.case.capability,
                question=prepared.case.question,
                trial=trial,
                passed=passed,
                status=observation.status,
                duration_seconds=duration,
                answer=observation.answer,
                missing_facts=missing,
                error=observation.error,
                plan=observation.plan,
            )
            attempts.append(attempt)
            if progress is not None:
                progress(attempt)
    return tuple(attempts)


def missing_facts(answer: str, facts: Sequence[RequiredFact]) -> tuple[str, ...]:
    normalized_answer = _normalize(answer)
    segments = tuple(_normalize(segment) for segment in re.split(r"[;\n]", answer))
    missing: list[str] = []
    for fact in facts:
        candidates = (
            (normalized_answer,)
            if not fact.context
            else tuple(
                segment
                for segment in segments
                if all(_contains_fragment(segment, item) for item in fact.context)
            )
        )
        if not any(
            all(_contains_fragment(candidate, value) for value in fact.values)
            for candidate in candidates
        ):
            missing.append(fact.describe())
    return tuple(missing)


def summarize(attempts: Sequence[EvaluationAttempt]) -> EvaluationSummary:
    count = len(attempts)
    passed = sum(attempt.passed for attempt in attempts)
    rate = passed / count if count else 0.0
    low, high = _wilson_interval(passed, count)
    latencies = sorted(attempt.duration_seconds for attempt in attempts)
    p95_index = max(0, math.ceil(0.95 * len(latencies)) - 1) if latencies else 0
    capabilities: list[CapabilitySummary] = []
    for capability in sorted({attempt.capability for attempt in attempts}):
        capability_attempts = tuple(
            attempt for attempt in attempts if attempt.capability == capability
        )
        capability_passed = sum(attempt.passed for attempt in capability_attempts)
        capabilities.append(
            CapabilitySummary(
                capability=capability,
                attempts=len(capability_attempts),
                passed=capability_passed,
                pass_rate=capability_passed / len(capability_attempts),
            )
        )
    return EvaluationSummary(
        attempts=count,
        passed=passed,
        pass_rate=rate,
        confidence_95_low=low,
        confidence_95_high=high,
        mean_latency_seconds=mean(latencies) if latencies else 0.0,
        p95_latency_seconds=latencies[p95_index] if latencies else 0.0,
        capabilities=tuple(capabilities),
    )


def _required_facts(
    query: OracleQuery,
    sales: Sequence[OracleSale],
) -> tuple[RequiredFact, ...]:
    if isinstance(query, AggregateOracle):
        aggregate_rows = _aggregate(query, sales)
        if not aggregate_rows:
            return (RequiredFact((), ("Não foram encontradas vendas",)),)
        facts: list[RequiredFact] = []
        for row in aggregate_rows:
            if row.dimensions:
                values = tuple(
                    _format_metric(metric, value) for metric, value in row.metrics
                )
            elif len(row.metrics) == 1:
                metric, value = row.metrics[0]
                values = (_format_metric(metric, value),)
            else:
                values = tuple(
                    f"{_metric_label(metric)}={_format_metric(metric, value)}"
                    for metric, value in row.metrics
                )
            facts.append(RequiredFact(row.dimensions, values))
        return tuple(facts)

    comparison_rows = _compare(query, sales)
    if not comparison_rows:
        return (RequiredFact((), ("Não foram encontradas vendas",)),)
    return tuple(
        RequiredFact(
            row.dimensions,
            tuple(_format_comparison_metric(metric) for metric in row.metrics),
        )
        for row in comparison_rows
    )


def _aggregate(
    query: AggregateOracle,
    sales: Sequence[OracleSale],
) -> tuple[_AggregateRow, ...]:
    matching = tuple(
        sale
        for sale in sales
        if query.period.contains(sale.sold_at) and _matches_filters(sale, query.filters)
    )
    grouped = _group_sales(matching, query.dimensions)
    rows = [
        _AggregateRow(
            dimensions=key,
            metrics=tuple((metric, _calculate_metric(metric, group)) for metric in query.metrics),
        )
        for key, group in grouped.items()
        if group
    ]
    rows.sort(key=lambda row: row.dimensions)
    if query.sort is not None:
        sort_spec = query.sort
        rows.sort(
            key=lambda row: row.metric(sort_spec.metric),
            reverse=sort_spec.direction == "desc",
        )
    if query.limit is not None:
        rows = rows[: query.limit]
    return tuple(rows)


def _compare(
    query: CompareOracle,
    sales: Sequence[OracleSale],
) -> tuple[_ComparisonRow, ...]:
    filtered = tuple(sale for sale in sales if _matches_filters(sale, query.filters))
    current = _group_sales(
        (sale for sale in filtered if query.current_period.contains(sale.sold_at)),
        query.dimensions,
    )
    baseline = _group_sales(
        (sale for sale in filtered if query.baseline_period.contains(sale.sold_at)),
        query.dimensions,
    )
    keys = sorted(set(current) | set(baseline))
    rows: list[_ComparisonRow] = []
    for key in keys:
        current_sales = current.get(key, ())
        baseline_sales = baseline.get(key, ())
        metrics: list[_ComparisonMetric] = []
        for metric_name in query.metrics:
            current_raw = _calculate_raw_metric(metric_name, current_sales)
            baseline_raw = _calculate_raw_metric(metric_name, baseline_sales)
            absolute_raw = current_raw - baseline_raw
            current_value = _rendered_metric_value(metric_name, current_raw)
            baseline_value = _rendered_metric_value(metric_name, baseline_raw)
            absolute = _rendered_metric_value(metric_name, absolute_raw)
            percentage = (
                None
                if baseline_raw == 0
                else (
                    Decimal(absolute_raw) * Decimal(100) / abs(Decimal(baseline_raw))
                ).quantize(PERCENT_QUANTUM)
            )
            metrics.append(
                _ComparisonMetric(
                    metric_name,
                    current_value,
                    baseline_value,
                    absolute,
                    percentage,
                )
            )
        rows.append(_ComparisonRow(key, tuple(metrics)))

    if query.sort is not None:
        sort_spec = query.sort
        non_null: list[_ComparisonRow] = []
        null: list[_ComparisonRow] = []
        for row in rows:
            value = _comparison_sort_value(row.metric(sort_spec.metric), sort_spec.comparison)
            (null if value is None else non_null).append(row)

        def sort_value(row: _ComparisonRow) -> MetricValue:
            value = _comparison_sort_value(
                row.metric(sort_spec.metric), sort_spec.comparison
            )
            if value is None:
                raise AssertionError("linhas sem valor devem ser ordenadas separadamente")
            return value

        non_null.sort(
            key=sort_value,
            reverse=sort_spec.direction == "desc",
        )
        rows = non_null + null
    if query.limit is not None:
        rows = rows[: query.limit]
    return tuple(rows)


def _group_sales(
    sales: Iterable[OracleSale],
    dimensions: tuple[DimensionName, ...],
) -> dict[tuple[str, ...], tuple[OracleSale, ...]]:
    groups: dict[tuple[str, ...], list[OracleSale]] = {}
    for sale in sales:
        key = tuple(_dimension_value(sale, dimension) for dimension in dimensions)
        groups.setdefault(key, []).append(sale)
    return {key: tuple(value) for key, value in groups.items()}


def _dimension_value(sale: OracleSale, dimension: DimensionName) -> str:
    if dimension == "product":
        return sale.product
    if dimension == "category":
        return sale.category
    if dimension == "customer":
        return sale.customer
    if dimension == "day":
        return sale.sold_at.strftime("%Y-%m-%d")
    if dimension == "week":
        iso_year, iso_week, _ = sale.sold_at.isocalendar()
        return f"{iso_year}-W{iso_week:02d}"
    if dimension == "month":
        return sale.sold_at.strftime("%Y-%m")
    return sale.sold_at.strftime("%Y")


def _calculate_metric(metric: MetricName, sales: Sequence[OracleSale]) -> MetricValue:
    return _rendered_metric_value(metric, _calculate_raw_metric(metric, sales))


def _calculate_raw_metric(metric: MetricName, sales: Sequence[OracleSale]) -> MetricValue:
    if metric == "revenue":
        return sum((sale.total_amount for sale in sales), start=Decimal())
    if metric == "sale_count":
        return len(sales)
    if metric == "units_sold":
        return sum(sale.quantity for sale in sales)
    if not sales:
        return Decimal()
    return sum((sale.total_amount for sale in sales), start=Decimal()) / len(sales)


def _rendered_metric_value(metric: MetricName, value: MetricValue) -> MetricValue:
    if metric in {"revenue", "average_ticket"}:
        return Decimal(value).quantize(MONEY_QUANTUM)
    return int(value)


def _matches_filters(sale: OracleSale, filters: Sequence[OracleFilter]) -> bool:
    for item in filters:
        candidates = {
            "product": (sale.product, sale.product_sku),
            "category": (sale.category,),
            "customer": (sale.customer, sale.customer_email),
        }[item.field]
        lowered_candidates = tuple(candidate.casefold() for candidate in candidates)
        lowered_values = tuple(value.casefold() for value in item.values)
        if item.operator == "equals":
            matched = any(candidate == lowered_values[0] for candidate in lowered_candidates)
        elif item.operator == "contains":
            matched = any(
                lowered_values[0] in candidate for candidate in lowered_candidates
            )
        else:
            matched = any(candidate in lowered_values for candidate in lowered_candidates)
        if not matched:
            return False
    return True


def _comparison_sort_value(
    metric: _ComparisonMetric,
    comparison: ComparisonValue | None,
) -> MetricValue | None:
    selected = comparison or "percentage_change"
    if selected == "current":
        return metric.current
    if selected == "baseline":
        return metric.baseline
    if selected == "absolute_change":
        return metric.absolute_change
    return metric.percentage_change


def _format_comparison_metric(metric: _ComparisonMetric) -> str:
    percentage = (
        "indefinida"
        if metric.percentage_change is None
        else f"{_format_decimal(metric.percentage_change)}%"
    )
    return (
        f"{_metric_label(metric.name)} atual={_format_metric(metric.name, metric.current)}, "
        f"base={_format_metric(metric.name, metric.baseline)}, "
        f"diferença={_format_metric(metric.name, metric.absolute_change)}, "
        f"variação={percentage}"
    )


def _format_metric(metric: MetricName, value: MetricValue) -> str:
    if metric in {"revenue", "average_ticket"}:
        return f"R$ {_format_money(Decimal(value))}"
    return f"{int(value):,}".replace(",", ".")


def _metric_label(metric: MetricName) -> str:
    return {
        "revenue": "receita",
        "sale_count": "número de vendas",
        "units_sold": "unidades vendidas",
        "average_ticket": "ticket médio",
    }[metric]


def _format_money(value: Decimal) -> str:
    rendered = f"{value:,.2f}"
    return rendered.replace(",", "_").replace(".", ",").replace("_", ".")


def _format_decimal(value: Decimal) -> str:
    rendered = f"{value:.4f}".rstrip("0").rstrip(".")
    return rendered.replace(".", ",")


def _as_utc(value: datetime) -> datetime:
    if value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _normalize(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    without_accents = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " ".join(without_accents.split())


def _contains_fragment(normalized_text: str, fragment: str) -> bool:
    normalized_fragment = _normalize(fragment)
    if normalized_fragment and (
        normalized_fragment[0].isdigit() or normalized_fragment[-1].isdigit()
    ):
        left_boundary = (
            r"(?<![\d.,])" if normalized_fragment[0].isdigit() else ""
        )
        right_boundary = (
            r"(?!\d)" if normalized_fragment[-1].isdigit() else ""
        )
        return (
            re.search(
                f"{left_boundary}{re.escape(normalized_fragment)}{right_boundary}",
                normalized_text,
            )
            is not None
        )
    return normalized_fragment in normalized_text


def _wilson_interval(successes: int, total: int) -> tuple[float, float]:
    if total == 0:
        return 0.0, 0.0
    z = 1.96
    proportion = successes / total
    denominator = 1 + z**2 / total
    center = (proportion + z**2 / (2 * total)) / denominator
    margin = (
        z
        * math.sqrt(proportion * (1 - proportion) / total + z**2 / (4 * total**2))
        / denominator
    )
    return max(0.0, center - margin), min(1.0, center + margin)


def _ask_endpoint(base_url: str, question: str, timeout: float) -> HttpObservation:
    query = urlencode({"question": question, "include_plan": "true"})
    url = f"{base_url.rstrip('/')}/sales-insights?{query}"
    request = Request(url, headers={"Accept": "application/json"}, method="GET")
    try:
        with urlopen(request, timeout=timeout) as response:
            status = response.status
            body = response.read().decode("utf-8")
    except HTTPError as error:
        status = error.code
        body = error.read().decode("utf-8", errors="replace")
    except (TimeoutError, URLError) as error:
        return HttpObservation(None, None, f"{type(error).__name__}: {error}")

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return HttpObservation(status, None, "resposta HTTP não contém JSON válido")
    if not isinstance(payload, dict) or not isinstance(payload.get("answer"), str):
        detail = payload.get("detail") if isinstance(payload, dict) else payload
        rendered_detail = json.dumps(detail, ensure_ascii=False)
        if len(rendered_detail) > 1_000:
            rendered_detail = f"{rendered_detail[:997]}..."
        return HttpObservation(
            status,
            None,
            f"JSON não contém o campo textual 'answer'; detail={rendered_detail}",
        )
    plan = payload.get("plan")
    return HttpObservation(
        status,
        payload["answer"],
        plan=plan if isinstance(plan, dict) else None,
    )


def _print_prepared(prepared_cases: Sequence[PreparedCase]) -> None:
    print("Oracle determinístico calculado antes das requisições:")
    for prepared in prepared_cases:
        print(f"- {prepared.case.name}: {prepared.case.question}")
        for fact in prepared.required_facts:
            print(f"    {fact.describe()}")


def _print_attempt(attempt: EvaluationAttempt) -> None:
    outcome = "PASS" if attempt.passed else "FAIL"
    status = str(attempt.status) if attempt.status is not None else "sem resposta"
    print(
        f"[{outcome}] {attempt.case} tentativa {attempt.trial} "
        f"({status}, {attempt.duration_seconds:.2f}s)",
        flush=True,
    )
    if attempt.error:
        print(f"    erro: {attempt.error}")
    for missing in attempt.missing_facts:
        print(f"    ausente: {missing}")
    if not attempt.passed and attempt.answer:
        print(f"    resposta: {attempt.answer}")
    if not attempt.passed and attempt.plan:
        print(
            "    plano: "
            + json.dumps(attempt.plan, ensure_ascii=False, separators=(",", ":"))
        )


def _print_summary(
    summary: EvaluationSummary,
    attempts: Sequence[EvaluationAttempt],
) -> None:
    print("\nResumo")
    print(f"- acertos: {summary.passed}/{summary.attempts} ({summary.pass_rate:.2%})")
    print(
        "- intervalo de confiança de 95% (Wilson): "
        f"{summary.confidence_95_low:.2%} a {summary.confidence_95_high:.2%}"
    )
    print(
        f"- latência: média {summary.mean_latency_seconds:.2f}s; "
        f"p95 {summary.p95_latency_seconds:.2f}s"
    )
    print("- acurácia por capacidade:")
    for capability in summary.capabilities:
        print(
            f"    {capability.capability}: {capability.passed}/"
            f"{capability.attempts} ({capability.pass_rate:.2%})"
        )
    case_names = dict.fromkeys(attempt.case for attempt in attempts)
    for case_name in case_names:
        case_attempts = tuple(attempt for attempt in attempts if attempt.case == case_name)
        case_passed = sum(attempt.passed for attempt in case_attempts)
        print(f"- {case_name}: {case_passed}/{len(case_attempts)}")


def write_json_report(
    path: Path,
    prepared: Sequence[PreparedCase],
    attempts: Sequence[EvaluationAttempt],
    summary: EvaluationSummary,
) -> None:
    expectations = {
        item.case.name: [fact.describe() for fact in item.required_facts] for item in prepared
    }
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "expectations": expectations,
        "summary": asdict(summary),
        "attempts": [asdict(attempt) for attempt in attempts],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Calcula respostas esperadas diretamente do banco e mede quantas respostas "
            "do endpoint contêm todos os fatos obrigatórios."
        )
    )
    parser.add_argument(
        "--base-url",
        default=os.getenv("GARAGE_API_URL", DEFAULT_API_URL),
        help=f"URL base da API (padrão: {DEFAULT_API_URL}).",
    )
    parser.add_argument("--trials", type=int, default=3, help="Repetições por pergunta.")
    parser.add_argument(
        "--timeout",
        type=float,
        default=180.0,
        help="Timeout de cada requisição em segundos.",
    )
    parser.add_argument(
        "--minimum-pass-rate",
        type=float,
        default=1.0,
        help="Taxa mínima entre 0 e 1 para o processo retornar sucesso.",
    )
    parser.add_argument(
        "--case",
        action="append",
        choices=tuple(case.name for case in DEFAULT_CASES),
        dest="case_names",
        help="Executa somente o caso informado; pode ser repetido.",
    )
    parser.add_argument("--list-cases", action="store_true", help="Lista os casos e encerra.")
    parser.add_argument("--json-report", type=Path, help="Grava o relatório detalhado em JSON.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    load_runtime_env()
    parser = _parser()
    args = parser.parse_args(argv)
    if args.list_cases:
        for case in DEFAULT_CASES:
            print(f"{case.name}: {case.question}")
        return 0
    if args.trials < 1:
        parser.error("--trials deve ser positivo")
    if args.timeout <= 0:
        parser.error("--timeout deve ser positivo")
    if not 0 <= args.minimum_pass_rate <= 1:
        parser.error("--minimum-pass-rate deve estar entre 0 e 1")

    selected_names = set(args.case_names or ())
    cases = tuple(
        case for case in DEFAULT_CASES if not selected_names or case.name in selected_names
    )
    database_url = RelationalDatabaseSettings.from_env().url
    sales = load_oracle_sales(database_url)
    if not sales:
        parser.error("o banco configurado não contém vendas para construir o oracle")

    # This is deliberately complete before _ask_endpoint can be called.
    prepared = prepare_cases(cases, sales)
    _print_prepared(prepared)
    print(f"\nExecutando {len(cases) * args.trials} requisições...", flush=True)
    attempts = evaluate_batch(
        prepared,
        lambda question: _ask_endpoint(args.base_url, question, args.timeout),
        trials=args.trials,
        progress=_print_attempt,
    )
    summary = summarize(attempts)
    _print_summary(summary, attempts)
    if args.json_report is not None:
        write_json_report(args.json_report, prepared, attempts, summary)
        print(f"- relatório JSON: {args.json_report.resolve()}")
    return 0 if summary.pass_rate >= args.minimum_pass_rate else 1


if __name__ == "__main__":
    raise SystemExit(main())
