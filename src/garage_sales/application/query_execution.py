from typing import assert_never

from garage_sales.application.models import (
    RepositoryQuery,
    RepositoryQueryResult,
    RepositoryRecord,
    SalesQueryEvidence,
    SalesQueryPlan,
)
from garage_sales.domain.analytics import (
    AggregateSales,
    CompareSales,
    SalesAnalysisCursorError,
)
from garage_sales.domain.ports import RelationalPersistence, RelationalReadUnitOfWork


class RepositorySalesQueryExecutor:
    """Execute the closed analytics catalog through database aggregation."""

    def __init__(self, relational_persistence: RelationalPersistence) -> None:
        self._relational_persistence = relational_persistence

    def execute(
        self,
        *,
        plan: SalesQueryPlan,
        cursor: str | None = None,
    ) -> SalesQueryEvidence:
        results: list[RepositoryQueryResult] = []
        with self._relational_persistence.read() as repositories:
            for index, query in enumerate(plan.queries):
                query_cursor = cursor if index == 0 else None
                records = self._execute_query(query, repositories, cursor=query_cursor)
                results.append(RepositoryQueryResult(query=query, records=records))
        if cursor is not None and not plan.queries:
            raise SalesAnalysisCursorError("cursor exige uma consulta sales.compare")
        return SalesQueryEvidence(results=tuple(results))

    @staticmethod
    def _execute_query(
        query: RepositoryQuery,
        repositories: RelationalReadUnitOfWork,
        *,
        cursor: str | None = None,
    ) -> tuple[RepositoryRecord, ...]:
        if isinstance(query, AggregateSales):
            if cursor is not None:
                raise SalesAnalysisCursorError("cursor exige uma consulta sales.compare")
            return (repositories.analytics.aggregate(query),)
        if isinstance(query, CompareSales):
            return (repositories.analytics.compare(query, cursor=cursor),)
        assert_never(query)
