from unittest.mock import Mock

import pytest

from garage_sales.application import GetSalesInsightsUseCase, SalesInsight, SalesQueryPlan
from garage_sales.domain.analytics import AggregateSales, SalesMetric
from scripts.evaluate_sales_insights import EvaluationAttempt, summarize
from scripts.run_get_sales_insights_efficacy import (
    friendly_progress,
    print_friendly_summary,
    use_case_ask,
)


def _attempt(*, passed: bool) -> EvaluationAttempt:
    return EvaluationAttempt(
        case="annual_revenue",
        capability="total",
        question="Qual foi a receita de 2025?",
        trial=1,
        passed=passed,
        status=200 if passed else 422,
        duration_seconds=1.25,
        answer="R$ 2.309,78" if passed else "R$ 0,00",
        missing_facts=() if passed else ("resposta -> R$ 2.309,78",),
        error=None,
        plan={"queries": []},
    )


def test_use_case_adapter_retains_answer_and_typed_plan() -> None:
    use_case = Mock(spec=GetSalesInsightsUseCase)
    use_case.execute.return_value = SalesInsight(
        answer="O total foi R$ 2.309,78.",
        plan=SalesQueryPlan(
            queries=(AggregateSales(metrics=(SalesMetric.REVENUE,)),)
        ),
    )

    observation = use_case_ask(use_case)("Quanto vendeu?")

    assert observation.status == 200
    assert observation.answer == "O total foi R$ 2.309,78."
    assert observation.plan is not None
    queries = observation.plan["queries"]
    assert isinstance(queries, list)
    assert isinstance(queries[0], dict)
    assert queries[0]["metrics"] == ["revenue"]


def test_friendly_output_summarizes_success(
    capsys: pytest.CaptureFixture[str],
) -> None:
    attempt = _attempt(passed=True)
    progress = friendly_progress(1)

    progress(attempt)
    print_friendly_summary(summarize((attempt,)), (attempt,))

    output = capsys.readouterr().out
    assert "[01/01] PASSOU" in output
    assert "RESULTADO DE EFICÁCIA" in output
    assert "Perguntas corretas: 1/1 (100.00%)" in output
    assert "Todos os fatos determinísticos esperados" in output


def test_friendly_output_lists_failures(capsys: pytest.CaptureFixture[str]) -> None:
    attempt = _attempt(passed=False)

    print_friendly_summary(summarize((attempt,)), (attempt,))

    output = capsys.readouterr().out
    assert "Falhas encontradas (1)" in output
    assert "annual_revenue, tentativa 1" in output
    assert "Capacidades que precisam de atenção" in output
    assert "total: 0/1 (0.00%)" in output
