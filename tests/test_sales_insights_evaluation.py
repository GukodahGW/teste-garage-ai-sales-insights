from collections.abc import Iterator
from pathlib import Path

import pytest

from garage_sales.infrastructure.sqlalchemy.migrations import upgrade_database
from scripts.evaluate_sales_insights import (
    DEFAULT_CASES,
    EvaluationAttempt,
    HttpObservation,
    OracleSale,
    PreparedCase,
    RequiredFact,
    evaluate_batch,
    load_oracle_sales,
    missing_facts,
    prepare_cases,
    summarize,
)
from scripts.seed import seed_database


@pytest.fixture
def oracle_sales(tmp_path: Path) -> Iterator[tuple[OracleSale, ...]]:
    database_url = f"sqlite+pysqlite:///{(tmp_path / 'evaluation.db').as_posix()}"
    upgrade_database(database_url)
    seed_database(database_url)
    yield load_oracle_sales(database_url)


def _prepared_case(name: str, sales: tuple[OracleSale, ...]) -> PreparedCase:
    selected = tuple(case for case in DEFAULT_CASES if case.name == name)
    assert len(selected) == 1
    return prepare_cases(selected, sales)[0]


def test_oracle_calculates_expected_facts_before_http_evaluation(
    oracle_sales: tuple[OracleSale, ...],
) -> None:
    annual = _prepared_case("annual_revenue", oracle_sales)
    weekly = _prepared_case("best_week_by_revenue", oracle_sales)
    comparison = _prepared_case("month_over_month_revenue", oracle_sales)

    assert annual.required_facts == (RequiredFact((), ("R$ 2.309,78",)),)
    assert weekly.required_facts == (
        RequiredFact(("2025-W09",), ("R$ 552,68",)),
    )
    assert comparison.required_facts == (
        RequiredFact(
            (),
            (
                "receita atual=R$ 1.159,59, base=R$ 925,19, "
                "diferença=R$ 234,40, variação=25,3353%",
            ),
        ),
    )


def test_every_default_question_has_at_least_one_deterministic_fact(
    oracle_sales: tuple[OracleSale, ...],
) -> None:
    prepared = prepare_cases(DEFAULT_CASES, oracle_sales)

    assert len(prepared) == 50
    assert all(item.required_facts for item in prepared)
    assert {item.case.capability for item in prepared} >= {
        "comparison",
        "filter_and_ranking",
        "multiple_metrics",
        "two_dimensions",
    }
    all_metrics_comparison = next(
        item for item in prepared if item.case.name == "month_over_month_all_metrics"
    )
    comparison_values = " ".join(all_metrics_comparison.required_facts[0].values)
    assert "ticket médio atual=R$ 64,42" in comparison_values
    assert "variação=-2,517%" in comparison_values


def test_fact_matching_keeps_a_value_associated_with_its_group() -> None:
    expected = (RequiredFact(("Product E",), ("51",)),)

    assert missing_facts("Product A (51); Product E (12)", expected) == (
        "Product E -> 51",
    )
    assert missing_facts("Product A (12); Product E (51)", expected) == ()


def test_fact_matching_is_accent_and_case_insensitive_but_number_aware() -> None:
    expected = (
        RequiredFact(
            ("Category 1",),
            ("variação=25,3353%", "unidades vendidas atual=13"),
        ),
    )

    assert missing_facts(
        "CATEGORIA=category 1: VARIACAO=25,3353%, unidades vendidas atual=130",
        expected,
    )
    assert not missing_facts(
        "categoria=Category 1: variacao=25,3353%, unidades vendidas atual=13",
        expected,
    )


def test_repeated_batch_reports_empirical_pass_rate() -> None:
    prepared = PreparedCase(
        case=DEFAULT_CASES[0],
        required_facts=(RequiredFact((), ("R$ 2.309,78",)),),
    )
    observations = iter(
        (
            HttpObservation(
                200,
                "O total foi R$ 2.309,78.",
                plan={"queries": [{"metrics": ["revenue"]}]},
            ),
            HttpObservation(200, "O total foi R$ 999,00."),
            HttpObservation(503, None, "provedor indisponível"),
        )
    )

    attempts = evaluate_batch(
        (prepared,),
        lambda _: next(observations),
        trials=3,
    )
    summary = summarize(attempts)

    assert [attempt.passed for attempt in attempts] == [True, False, False]
    assert summary.attempts == 3
    assert summary.passed == 1
    assert summary.pass_rate == pytest.approx(1 / 3)
    assert 0 <= summary.confidence_95_low < summary.pass_rate
    assert summary.pass_rate < summary.confidence_95_high <= 1
    assert attempts[0].plan == {"queries": [{"metrics": ["revenue"]}]}
    assert summary.capabilities[0].capability == "total"
    assert summary.capabilities[0].passed == 1
    assert summary.capabilities[0].attempts == 3
    assert summary.capabilities[0].pass_rate == pytest.approx(1 / 3)


def test_progress_callback_receives_each_attempt() -> None:
    prepared = PreparedCase(
        case=DEFAULT_CASES[0],
        required_facts=(RequiredFact((), ("R$ 2.309,78",)),),
    )
    progress: list[EvaluationAttempt] = []

    attempts = evaluate_batch(
        (prepared,),
        lambda _: HttpObservation(200, "R$ 2.309,78"),
        trials=2,
        progress=progress.append,
    )

    assert tuple(progress) == attempts
    assert all(attempt.passed for attempt in attempts)
