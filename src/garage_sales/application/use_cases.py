from calendar import monthrange
from datetime import datetime

from garage_sales.application.models import SalesInsight, SalesMonth, TopProduct, TopProductsResult
from garage_sales.application.ports import (
    SalesInsightSynthesizer,
    SalesQueryExecutor,
    SalesQueryPlanner,
)
from garage_sales.domain.ports import RelationalPersistence

MAX_QUESTION_LENGTH = 2_000
TOP_PRODUCTS_LIMIT = 5


class GetSalesInsightsUseCase:
    """Orchestrate replaceable planning and synthesis around trusted data access."""

    def __init__(
        self,
        *,
        planner: SalesQueryPlanner,
        query_executor: SalesQueryExecutor,
        synthesizer: SalesInsightSynthesizer,
    ) -> None:
        self._planner = planner
        self._query_executor = query_executor
        self._synthesizer = synthesizer

    def execute(self, *, question: str, cursor: str | None = None) -> SalesInsight:
        normalized_question = question.strip()
        if not normalized_question:
            raise ValueError("question nao pode ser vazia")
        if len(normalized_question) > MAX_QUESTION_LENGTH:
            raise ValueError(f"question nao pode exceder {MAX_QUESTION_LENGTH} caracteres")

        plan = self._planner.plan(question=normalized_question)
        evidence = self._query_executor.execute(plan=plan, cursor=cursor)
        answer = self._synthesizer.synthesize(
            question=normalized_question,
            evidence=evidence,
        ).strip()
        if not answer:
            raise RuntimeError("o sintetizador retornou uma resposta vazia")
        next_cursor = None
        if evidence.results and evidence.results[0].records:
            next_cursor = evidence.results[0].records[0].next_cursor
        return SalesInsight(answer=answer, next_cursor=next_cursor, plan=plan)


class GetTopProductsUseCase:
    """Return the five best-selling products from the latest month with sales."""

    def __init__(
        self,
        *,
        relational_persistence: RelationalPersistence,
    ) -> None:
        self._relational_persistence = relational_persistence

    def execute(self) -> TopProductsResult:
        with self._relational_persistence.read() as repositories:
            latest_sale = repositories.sales.get_latest()
            if latest_sale is None:
                return TopProductsResult(reference_month=None, products=())

            latest_month_start, latest_month_end = _calendar_month_bounds(latest_sale.sold_at)
            reference_month = SalesMonth(
                year=latest_month_start.year,
                month=latest_month_start.month,
            )
            products = tuple(
                TopProduct.from_sales_total(total)
                for total in repositories.analytics.top_products(
                    sold_from=latest_month_start,
                    sold_until=latest_month_end,
                    limit=TOP_PRODUCTS_LIMIT,
                )
            )

        return TopProductsResult(
            reference_month=reference_month,
            products=products,
        )


def _calendar_month_bounds(reference: datetime) -> tuple[datetime, datetime]:
    month_start = reference.replace(
        day=1,
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )
    month_end = reference.replace(
        day=monthrange(reference.year, reference.month)[1],
        hour=23,
        minute=59,
        second=59,
        microsecond=999999,
    )
    return month_start, month_end
