from typing import Protocol

from garage_sales.application.models import (
    SalesInsight,
    SalesQueryEvidence,
    SalesQueryPlan,
    TopProductsResult,
)


class GetSalesInsights(Protocol):
    """Inbound port for the get-sales-insights use case."""

    def execute(self, *, question: str, cursor: str | None = None) -> SalesInsight: ...


class GetTopProducts(Protocol):
    """Inbound port for top products in the latest calendar month with sales."""

    def execute(self) -> TopProductsResult: ...


class SalesQueryPlanner(Protocol):
    """Outbound port that translates natural language into repository operations."""

    def plan(self, *, question: str) -> SalesQueryPlan: ...


class SalesQueryExecutor(Protocol):
    """Outbound port that obtains evidence without exposing persistence details."""

    def execute(
        self,
        *,
        plan: SalesQueryPlan,
        cursor: str | None = None,
    ) -> SalesQueryEvidence: ...


class SalesInsightSynthesizer(Protocol):
    """Outbound port that turns repository evidence into a natural-language answer."""

    def synthesize(self, *, question: str, evidence: SalesQueryEvidence) -> str: ...
