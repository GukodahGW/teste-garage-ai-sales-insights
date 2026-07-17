from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import assert_never, cast

from garage_sales.application.models import (
    CalculateSalesMetric,
    FindTopProducts,
    RepositoryQuery,
    RepositoryQueryResult,
    RepositoryRecord,
    SalesMetricValue,
    SalesQueryEvidence,
    SalesQueryPlan,
    TopProduct,
)
from garage_sales.domain.analytics import (
    AggregateSales,
    AnalysisDataset,
    AnalysisStatus,
    AnomalyAnalysis,
    BasketAnalysis,
    CohortAnalysis,
    CompareSales,
    ForecastSales,
    SalesAnalysisError,
    SalesMetric,
)
from garage_sales.domain.criteria import MAX_PAGE_SIZE, SaleCriteria
from garage_sales.domain.entities import Sale
from garage_sales.domain.ports import (
    RelationalAnalyticsReadUnitOfWork,
    RelationalPersistence,
    RelationalReadUnitOfWork,
)

MONEY_QUANTUM = Decimal("0.01")


class RepositorySalesQueryExecutor:
    """Execute the closed insight catalog and calculate every value deterministically."""

    def __init__(self, relational_persistence: RelationalPersistence) -> None:
        self._relational_persistence = relational_persistence

    def execute(self, *, plan: SalesQueryPlan) -> SalesQueryEvidence:
        results: list[RepositoryQueryResult] = []
        with self._relational_persistence.read() as repositories:
            for query in plan.queries:
                records = self._execute_query(query, repositories)
                results.append(RepositoryQueryResult(query=query, records=records))
        return SalesQueryEvidence(results=tuple(results))

    @staticmethod
    def _execute_query(
        query: RepositoryQuery,
        repositories: RelationalReadUnitOfWork,
    ) -> tuple[RepositoryRecord, ...]:
        if isinstance(query, CalculateSalesMetric):
            return (RepositorySalesQueryExecutor._calculate_metric(query, repositories),)
        if isinstance(query, FindTopProducts):
            return RepositorySalesQueryExecutor._find_top_products(query, repositories)
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
            analytics_repositories = cast(RelationalAnalyticsReadUnitOfWork, repositories)
            try:
                return (analytics_repositories.analytics.execute(query),)
            except SalesAnalysisError as error:
                return (
                    AnalysisDataset(
                        rows=(),
                        status=AnalysisStatus.UNSUPPORTED,
                        warnings=(str(error),),
                    ),
                )
        assert_never(query)

    @staticmethod
    def _find_all_sales(
        *,
        sold_from: datetime | None,
        sold_until: datetime | None,
        repositories: RelationalReadUnitOfWork,
    ) -> list[Sale]:
        # The public query is never silently truncated: every repository page is consumed
        # before a metric or ranking is calculated.
        sales: list[Sale] = []
        offset = 0
        while True:
            page = repositories.sales.find(
                SaleCriteria(
                    sold_from=sold_from,
                    sold_until=sold_until,
                    limit=MAX_PAGE_SIZE,
                    offset=offset,
                )
            )
            sales.extend(page)
            if len(page) < MAX_PAGE_SIZE:
                return sales
            offset += len(page)

    @staticmethod
    def _calculate_metric(
        query: CalculateSalesMetric,
        repositories: RelationalReadUnitOfWork,
    ) -> SalesMetricValue:
        sales = RepositorySalesQueryExecutor._find_all_sales(
            sold_from=query.sold_from,
            sold_until=query.sold_until,
            repositories=repositories,
        )
        matched_sales = len(sales)

        if query.metric is SalesMetric.REVENUE:
            value: Decimal | int = sum(
                (sale.total_amount for sale in sales),
                start=Decimal("0.00"),
            ).quantize(MONEY_QUANTUM)
        elif query.metric is SalesMetric.SALE_COUNT:
            value = matched_sales
        elif query.metric is SalesMetric.UNITS_SOLD:
            value = sum(sale.quantity for sale in sales)
        elif query.metric is SalesMetric.AVERAGE_TICKET:
            revenue = sum(
                (sale.total_amount for sale in sales),
                start=Decimal("0.00"),
            )
            value = (
                Decimal("0.00")
                if matched_sales == 0
                else (revenue / matched_sales).quantize(
                    MONEY_QUANTUM,
                    rounding=ROUND_HALF_UP,
                )
            )
        else:
            raise ValueError(f"metrica legada nao suportada: {query.metric.value}")

        return SalesMetricValue(
            metric=query.metric,
            value=value,
            matched_sales=matched_sales,
        )

    @staticmethod
    def _find_top_products(
        query: FindTopProducts,
        repositories: RelationalReadUnitOfWork,
    ) -> tuple[TopProduct, ...]:
        sales = RepositorySalesQueryExecutor._find_all_sales(
            sold_from=query.sold_from,
            sold_until=query.sold_until,
            repositories=repositories,
        )
        quantities_by_product: dict[int, int] = {}
        for sale in sales:
            if sale.product_id is None or sale.quantity <= 0:
                continue
            quantities_by_product[sale.product_id] = (
                quantities_by_product.get(sale.product_id, 0) + sale.quantity
            )

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
            if len(result) == query.limit:
                break
        return tuple(result)
