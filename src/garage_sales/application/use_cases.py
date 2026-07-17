from calendar import monthrange
from datetime import datetime

from garage_sales.application.models import (
    SalesInsight,
    SalesMonth,
    TopProduct,
    TopProductsResult,
)
from garage_sales.application.ports import (
    SalesInsightSynthesizer,
    SalesQueryExecutor,
    SalesQueryPlanner,
)
from garage_sales.domain.analytics import AnalysisDataset, AnalysisStatus
from garage_sales.domain.criteria import MAX_PAGE_SIZE, SaleCriteria
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

    def execute(self, *, question: str) -> SalesInsight:
        normalized_question = question.strip()
        if not normalized_question:
            raise ValueError("question nao pode ser vazia")
        if len(normalized_question) > MAX_QUESTION_LENGTH:
            raise ValueError(f"question nao pode exceder {MAX_QUESTION_LENGTH} caracteres")

        plan = self._planner.plan(question=normalized_question)
        evidence = self._query_executor.execute(plan=plan)
        answer = self._synthesizer.synthesize(
            question=normalized_question,
            evidence=evidence,
        ).strip()
        if not answer:
            raise RuntimeError("o sintetizador retornou uma resposta vazia")
        datasets = tuple(
            record
            for result in evidence.results
            for record in result.records
            if isinstance(record, AnalysisDataset)
        )
        warnings = tuple(
            dict.fromkeys(warning for dataset in datasets for warning in dataset.warnings)
        )
        if not evidence.results:
            insight_status = AnalysisStatus.UNSUPPORTED
        elif any(dataset.status is AnalysisStatus.AMBIGUOUS for dataset in datasets):
            insight_status = AnalysisStatus.AMBIGUOUS
        elif any(dataset.status is AnalysisStatus.UNSUPPORTED for dataset in datasets):
            insight_status = AnalysisStatus.UNSUPPORTED
        elif datasets and all(dataset.status is AnalysisStatus.NO_DATA for dataset in datasets):
            insight_status = AnalysisStatus.NO_DATA
        else:
            insight_status = AnalysisStatus.ANSWERED
        return SalesInsight(
            answer=answer,
            status=insight_status,
            data=datasets,
            warnings=warnings,
        )


class GetTopProductsUseCase:
    """Return the five best-selling products from the latest month with sales."""

    def __init__(
        self,
        *,
        relational_persistence: RelationalPersistence,
    ) -> None:
        self._relational_persistence = relational_persistence

    def execute(self) -> TopProductsResult:
        quantities_by_product: dict[int, int] = {}
        offset = 0

        with self._relational_persistence.read() as repositories:
            latest_sale = repositories.sales.get_latest()
            if latest_sale is None:
                return TopProductsResult(reference_month=None, products=())

            latest_month_start, latest_month_end = _calendar_month_bounds(latest_sale.sold_at)
            reference_month = SalesMonth(
                year=latest_month_start.year,
                month=latest_month_start.month,
            )
            while True:
                sales = repositories.sales.find(
                    SaleCriteria(
                        sold_from=latest_month_start,
                        sold_until=latest_month_end,
                        limit=MAX_PAGE_SIZE,
                        offset=offset,
                    )
                )
                for sale in sales:
                    if sale.product_id is None or sale.quantity <= 0:
                        continue
                    quantities_by_product[sale.product_id] = (
                        quantities_by_product.get(sale.product_id, 0) + sale.quantity
                    )

                if len(sales) < MAX_PAGE_SIZE:
                    break
                offset += len(sales)

            ranked_quantities = sorted(
                quantities_by_product.items(),
                key=lambda item: (-item[1], item[0]),
            )
            result: list[TopProduct] = []
            for product_id, quantity_sold in ranked_quantities:
                product = repositories.products.get_by_id(product_id)
                if product is None:
                    continue
                result.append(
                    TopProduct(
                        product_id=product.id,
                        sku=product.sku,
                        name=product.name,
                        quantity_sold=quantity_sold,
                    )
                )
                if len(result) == TOP_PRODUCTS_LIMIT:
                    break

        return TopProductsResult(
            reference_month=reference_month,
            products=tuple(result),
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
