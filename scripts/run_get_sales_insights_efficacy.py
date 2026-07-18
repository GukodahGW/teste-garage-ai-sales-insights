"""Executa as 50 avaliações de eficácia diretamente no GetSalesInsightsUseCase."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from fastapi.encoders import jsonable_encoder

from garage_sales.adapters.langchain import LangChainSalesQueryPlanner, build_chat_model
from garage_sales.application import (
    DeterministicSalesInsightSynthesizer,
    GetSalesInsightsUseCase,
)
from garage_sales.bootstrap import build_get_sales_insights, build_relational_persistence
from garage_sales.config import (
    LlmProviderSettings,
    RelationalDatabaseSettings,
    SalesQueryPlannerSettings,
    load_runtime_env,
)
from garage_sales.infrastructure.sqlalchemy.database import SqlAlchemyRelationalPersistence
from scripts.evaluate_sales_insights import (
    DEFAULT_CASES,
    EvaluationAttempt,
    EvaluationSummary,
    HttpObservation,
    evaluate_batch,
    load_oracle_sales,
    prepare_cases,
    summarize,
    write_json_report,
)

DEFAULT_REPORT = Path(".reports/get-sales-insights-efficacy.json")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Executa diretamente o GetSalesInsightsUseCase para as 50 perguntas e "
            "compara as respostas com um oracle determinístico."
        )
    )
    parser.add_argument(
        "--trials",
        type=int,
        default=1,
        help="Número de execuções de cada uma das 50 perguntas (padrão: 1).",
    )
    parser.add_argument(
        "--minimum-pass-rate",
        type=float,
        default=1.0,
        help="Taxa mínima, entre 0 e 1, para retornar sucesso (padrão: 1.0).",
    )
    parser.add_argument(
        "--json-report",
        type=Path,
        default=DEFAULT_REPORT,
        help=f"Caminho do relatório detalhado (padrão: {DEFAULT_REPORT}).",
    )
    return parser


def build_runtime_use_case() -> tuple[
    GetSalesInsightsUseCase,
    SqlAlchemyRelationalPersistence,
]:
    """Compose the real use case without starting the HTTP server."""

    database_settings = RelationalDatabaseSettings.from_env()
    planner_settings = SalesQueryPlannerSettings.from_env()
    planner = LangChainSalesQueryPlanner(
        build_chat_model(LlmProviderSettings.from_env()),
        max_date_validation_retries=planner_settings.date_validation_max_retries,
        max_filter_validation_retries=planner_settings.filter_validation_max_retries,
    )
    persistence = build_relational_persistence(database_settings)
    use_case = build_get_sales_insights(
        relational_persistence=persistence,
        planner=planner,
        synthesizer=DeterministicSalesInsightSynthesizer(),
    )
    return use_case, persistence


def use_case_ask(use_case: GetSalesInsightsUseCase) -> Callable[[str], HttpObservation]:
    """Adapt a direct use-case execution to the shared evaluation contract."""

    def ask(question: str) -> HttpObservation:
        result = use_case.execute(question=question)
        encoded_plan = jsonable_encoder(result.plan)
        return HttpObservation(
            status=200,
            answer=result.answer,
            plan=encoded_plan if isinstance(encoded_plan, dict) else None,
        )

    return ask


def friendly_progress(total: int) -> Callable[[EvaluationAttempt], None]:
    completed = 0

    def print_attempt(attempt: EvaluationAttempt) -> None:
        nonlocal completed
        completed += 1
        outcome = "PASSOU" if attempt.passed else "FALHOU"
        print(
            f"[{completed:02d}/{total:02d}] {outcome:<6} "
            f"{attempt.case} ({attempt.duration_seconds:.2f}s)",
            flush=True,
        )
        if attempt.error:
            print(f"           erro: {attempt.error}")
        for missing in attempt.missing_facts:
            print(f"           fato esperado ausente: {missing}")

    return print_attempt


def print_friendly_summary(
    summary: EvaluationSummary,
    attempts: Sequence[EvaluationAttempt],
) -> None:
    failed = tuple(attempt for attempt in attempts if not attempt.passed)
    elapsed = sum(attempt.duration_seconds for attempt in attempts)
    capability_count = len(summary.capabilities)
    passing_capabilities = sum(
        capability.passed == capability.attempts
        for capability in summary.capabilities
    )
    assessment = _assessment(summary.pass_rate)

    print("\n" + "=" * 68)
    print("RESULTADO DE EFICÁCIA — GET SALES INSIGHTS")
    print("=" * 68)
    print(f"Avaliação:          {assessment}")
    print(
        f"Perguntas corretas: {summary.passed}/{summary.attempts} "
        f"({summary.pass_rate:.2%})"
    )
    print(
        "Confiança 95%:     "
        f"{summary.confidence_95_low:.2%} a {summary.confidence_95_high:.2%} "
        "(Wilson)"
    )
    print(f"Tempo total:        {elapsed:.2f}s")
    print(f"Latência média:     {summary.mean_latency_seconds:.2f}s")
    print(f"Latência p95:       {summary.p95_latency_seconds:.2f}s")
    print(
        f"Capacidades:        {passing_capabilities}/{capability_count} "
        "sem falhas"
    )

    if not failed:
        print("\nTodos os fatos determinísticos esperados apareceram nas respostas.")
        return

    print(f"\nFalhas encontradas ({len(failed)}):")
    for attempt in failed:
        print(f"- {attempt.case}, tentativa {attempt.trial}")
        if attempt.answer:
            print(f"  resposta: {attempt.answer}")
        if attempt.error:
            print(f"  erro: {attempt.error}")
        for missing in attempt.missing_facts:
            print(f"  ausente: {missing}")

    failing_capabilities = tuple(
        capability
        for capability in summary.capabilities
        if capability.passed != capability.attempts
    )
    print("\nCapacidades que precisam de atenção:")
    for capability in failing_capabilities:
        print(
            f"- {capability.capability}: {capability.passed}/"
            f"{capability.attempts} ({capability.pass_rate:.2%})"
        )


def _assessment(pass_rate: float) -> str:
    if pass_rate >= 0.98:
        return "EXCELENTE nesta execução"
    if pass_rate >= 0.90:
        return "BOA, com poucos casos para investigar"
    if pass_rate >= 0.75:
        return "ATENÇÃO, há regressões relevantes"
    return "CRÍTICA, requer investigação"


def main(argv: Sequence[str] | None = None) -> int:
    load_runtime_env()
    parser = _parser()
    args = parser.parse_args(argv)
    if args.trials < 1:
        parser.error("--trials deve ser positivo")
    if not 0 <= args.minimum_pass_rate <= 1:
        parser.error("--minimum-pass-rate deve estar entre 0 e 1")

    database_settings = RelationalDatabaseSettings.from_env()
    try:
        sales = load_oracle_sales(database_settings.url)
    except Exception as error:
        print(f"Não foi possível carregar o oracle: {error}", file=sys.stderr)
        return 2
    if not sales:
        print("O banco configurado não contém vendas para avaliar.", file=sys.stderr)
        return 2

    prepared = prepare_cases(DEFAULT_CASES, sales)
    total = len(prepared) * args.trials
    print("=" * 68)
    print("AVALIAÇÃO DIRETA DO GET SALES INSIGHTS USE CASE")
    print("=" * 68)
    print(f"Perguntas: {len(prepared)} | trials por pergunta: {args.trials}")
    print("O oracle determinístico foi calculado; iniciando o use case...\n")

    persistence: SqlAlchemyRelationalPersistence | None = None
    try:
        use_case, persistence = build_runtime_use_case()
        attempts = evaluate_batch(
            prepared,
            use_case_ask(use_case),
            trials=args.trials,
            progress=friendly_progress(total),
        )
    except Exception as error:
        print(f"Não foi possível iniciar a avaliação: {error}", file=sys.stderr)
        return 2
    finally:
        if persistence is not None:
            persistence.dispose()

    summary = summarize(attempts)
    print_friendly_summary(summary, attempts)
    write_json_report(args.json_report, prepared, attempts, summary)
    print(f"\nRelatório detalhado: {args.json_report.resolve()}")
    return 0 if summary.pass_rate >= args.minimum_pass_rate else 1


if __name__ == "__main__":
    raise SystemExit(main())
