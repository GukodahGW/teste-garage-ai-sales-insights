from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from langchain_core.exceptions import OutputParserException
from langchain_core.language_models.fake_chat_models import FakeListChatModel

from garage_sales.adapters.langchain import (
    LangChainPlanningError,
    LangChainSalesQueryPlanner,
    PlannerFilterValidationError,
    QuestionFilterConstraint,
    build_planner_validation_feedback,
    extract_question_filter_constraints,
    validate_question_filter_constraints,
)
from garage_sales.application import (
    AggregateSales,
    AnalysisCell,
    AnalysisRow,
    CompareSales,
    DeterministicSalesInsightSynthesizer,
    FilterOperator,
    GetSalesInsightsUseCase,
    RepositoryQueryResult,
    RepositorySalesQueryExecutor,
    SalesAnalysisResult,
    SalesDimension,
    SalesFilter,
    SalesFilterField,
    SalesMetric,
    SalesQueryEvidence,
    SalesQueryPlan,
    SortSpec,
    TimePeriod,
)
from garage_sales.infrastructure.sqlalchemy import SqlAlchemyRelationalPersistence
from garage_sales.infrastructure.sqlalchemy.migrations import upgrade_database
from scripts.seed import seed_database


def _period(year: int) -> TimePeriod:
    return TimePeriod(
        start=datetime(year, 1, 1, tzinfo=UTC),
        end=datetime(year, 12, 31, 23, 59, 59, 999999, tzinfo=UTC),
    )


@pytest.mark.parametrize(
    ("metric", "question"),
    [
        (SalesMetric.REVENUE, "Qual foi o total de vendas de 2025?"),
        (SalesMetric.SALE_COUNT, "Quantas vendas tivemos em 2025?"),
        (SalesMetric.UNITS_SOLD, "Quantas unidades foram vendidas em 2025?"),
        (SalesMetric.AVERAGE_TICKET, "Qual foi o ticket medio de 2025?"),
    ],
)
def test_planner_maps_fundamental_metrics_to_aggregate(
    metric: SalesMetric,
    question: str,
) -> None:
    planner = LangChainSalesQueryPlanner(
        FakeListChatModel(
            responses=[
                f'''{{
                    "calls": [{{
                        "operation": "sales.aggregate",
                        "metrics": ["{metric.value}"],
                        "period": {{
                            "start": "2025-01-01T00:00:00Z",
                            "end": "2025-12-31T23:59:59.999999Z"
                        }}
                    }}]
                }}'''
            ]
        )
    )

    assert planner.plan(question=question).queries == (
        AggregateSales(metrics=(metric,), period=_period(2025)),
    )


def test_planner_maps_weekly_ranking_to_grouped_aggregate() -> None:
    planner = LangChainSalesQueryPlanner(
        FakeListChatModel(
            responses=[
                """{
                    "calls": [{
                        "operation": "sales.aggregate",
                        "metrics": ["revenue"],
                        "dimensions": ["week"],
                        "period": {
                            "start": "2025-01-01T00:00:00Z",
                            "end": "2025-12-31T23:59:59.999999Z"
                        },
                        "sort": [{"metric": "revenue", "direction": "desc"}],
                        "limit": 1
                    }]
                }"""
            ]
        )
    )

    assert planner.plan(question="Qual foi a semana de 2025 que mais vendeu?").queries == (
        AggregateSales(
            metrics=(SalesMetric.REVENUE,),
            dimensions=(SalesDimension.WEEK,),
            period=_period(2025),
            sort=(SortSpec(SalesMetric.REVENUE),),
            limit=1,
        ),
    )


def test_planner_maps_period_comparison() -> None:
    planner = LangChainSalesQueryPlanner(
        FakeListChatModel(
            responses=[
                """{
                    "calls": [{
                        "operation": "sales.compare",
                        "metrics": ["revenue"],
                        "current_period": {
                            "start": "2026-01-01T00:00:00Z",
                            "end": "2026-12-31T23:59:59.999999Z"
                        },
                        "baseline_period": {
                            "start": "2025-01-01T00:00:00Z",
                            "end": "2025-12-31T23:59:59.999999Z"
                        }
                    }]
                }"""
            ]
        )
    )

    assert planner.plan(question="Quanto crescemos de 2025 para 2026?").queries == (
        CompareSales(
            metrics=(SalesMetric.REVENUE,),
            current_period=_period(2026),
            baseline_period=_period(2025),
        ),
    )


def test_calendar_handler_explains_and_corrects_a_non_leap_february() -> None:
    error = OutputParserException(
        "invalid date",
        llm_output=(
            '{"current_period":{"start":"2025-02-01T00:00:00Z",'
            '"end":"2025-02-29T23:59:59.999999Z"}}'
        ),
    )

    feedback = build_planner_validation_feedback(error)

    assert "validacao deterministica do calendario gregoriano" in feedback
    assert "2025-02-29 nao existe" in feedback
    assert "dias de 01 a 28" in feedback
    assert "use 2025-02-28" in feedback
    assert "Gere novamente o JSON completo" in feedback


def test_calendar_handler_does_not_reject_a_valid_leap_day() -> None:
    error = OutputParserException(
        "another validation failure",
        llm_output='{"end":"2024-02-29T23:59:59.999999Z"}',
    )

    feedback = build_planner_validation_feedback(error)

    assert "calendario gregoriano" not in feedback
    assert feedback.startswith("Plano invalido: OutputParserException")


def test_planner_retries_an_invalid_calendar_date_with_a_complete_new_plan() -> None:
    invalid_response = """{
        "calls": [{
            "operation": "sales.compare",
            "metrics": ["revenue"],
            "current_period": {
                "start": "2025-02-01T00:00:00Z",
                "end": "2025-02-29T23:59:59.999999Z"
            },
            "baseline_period": {
                "start": "2025-01-01T00:00:00Z",
                "end": "2025-01-31T23:59:59.999999Z"
            }
        }]
    }"""
    valid_response = invalid_response.replace("2025-02-29", "2025-02-28")
    planner = LangChainSalesQueryPlanner(
        FakeListChatModel(responses=[invalid_response, valid_response]),
        max_attempts=1,
        max_date_validation_retries=1,
    )

    plan = planner.plan(
        question="Compare a receita de fevereiro de 2025 com janeiro de 2025."
    )

    assert plan.queries == (
        CompareSales(
            metrics=(SalesMetric.REVENUE,),
            current_period=TimePeriod(
                datetime(2025, 2, 1, tzinfo=UTC),
                datetime(2025, 2, 28, 23, 59, 59, 999999, tzinfo=UTC),
            ),
            baseline_period=TimePeriod(
                datetime(2025, 1, 1, tzinfo=UTC),
                datetime(2025, 1, 31, 23, 59, 59, 999999, tzinfo=UTC),
            ),
        ),
    )


def test_planner_stops_after_the_configured_date_retry_limit() -> None:
    invalid_response = """{
        "calls": [{
            "operation": "sales.compare",
            "metrics": ["revenue"],
            "current_period": {
                "start": "2025-02-01T00:00:00Z",
                "end": "2025-02-29T23:59:59.999999Z"
            },
            "baseline_period": {
                "start": "2025-01-01T00:00:00Z",
                "end": "2025-01-31T23:59:59.999999Z"
            }
        }]
    }"""
    model = FakeListChatModel(responses=[invalid_response] * 4)
    planner = LangChainSalesQueryPlanner(
        model,
        max_attempts=1,
        max_date_validation_retries=2,
    )

    with pytest.raises(
        LangChainPlanningError,
        match=r"apos 3 tentativas; retries de data usados: 2/2",
    ):
        planner.plan(question="Compare fevereiro de 2025 com janeiro de 2025")

    assert model.i == 3


def test_planner_projects_out_a_grouping_dimension_not_requested_by_the_question() -> None:
    grouped_response = """{
        "calls": [{
            "operation": "sales.compare",
            "metrics": ["revenue"],
            "current_period": {
                "start": "2025-02-01T00:00:00Z",
                "end": "2025-02-28T23:59:59.999999Z"
            },
            "baseline_period": {
                "start": "2025-01-01T00:00:00Z",
                "end": "2025-01-31T23:59:59.999999Z"
            },
            "dimensions": ["month"]
        }]
    }"""
    planner = LangChainSalesQueryPlanner(
        FakeListChatModel(responses=[grouped_response]),
        max_attempts=1,
    )

    plan = planner.plan(
        question="Compare a receita de fevereiro de 2025 com janeiro de 2025."
    )

    query = plan.queries[0]
    assert isinstance(query, CompareSales)
    assert query.dimensions == ()


def test_planner_keeps_a_temporal_dimension_explicitly_requested_by_the_question() -> None:
    planner = LangChainSalesQueryPlanner(
        FakeListChatModel(
            responses=[
                """{
                    "calls": [{
                        "operation": "sales.aggregate",
                        "metrics": ["revenue"],
                        "period": {
                            "start": "2025-01-01T00:00:00Z",
                            "end": "2025-12-31T23:59:59.999999Z"
                        },
                        "dimensions": ["month"]
                    }]
                }"""
            ]
        )
    )

    plan = planner.plan(question="Mostre a receita de cada mês de 2025")

    query = plan.queries[0]
    assert isinstance(query, AggregateSales)
    assert query.dimensions == (SalesDimension.MONTH,)


def test_filter_constraint_extractor_preserves_structured_literals() -> None:
    constraints = extract_question_filter_constraints(
        "Compare Category 2, Product A, Product C, SKU005 e jane@example.com."
    )

    assert constraints == (
        QuestionFilterConstraint(SalesFilterField.CATEGORY, ("Category 2",)),
        QuestionFilterConstraint(
            SalesFilterField.PRODUCT,
            ("Product A", "Product C", "SKU005"),
        ),
        QuestionFilterConstraint(SalesFilterField.CUSTOMER, ("jane@example.com",)),
    )


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        (
            "Mostre receita por produto em 2025 para Product A, Product C e Product E.",
            QuestionFilterConstraint(
                SalesFilterField.PRODUCT,
                ("Product A", "Product C", "Product E"),
            ),
        ),
        (
            "Quantas unidades do produto SKU005 foram vendidas?",
            QuestionFilterConstraint(SalesFilterField.PRODUCT, ("SKU005",)),
        ),
    ],
)
def test_filter_constraint_extractor_ignores_portuguese_grammar_words(
    question: str,
    expected: QuestionFilterConstraint,
) -> None:
    assert extract_question_filter_constraints(question) == (expected,)


def test_filter_validation_feedback_is_specific_and_requests_complete_regeneration() -> None:
    feedback = build_planner_validation_feedback(
        PlannerFilterValidationError(
            "A pergunta exige category=['Category 2'], mas o plano produziu ['2']."
        )
    )

    assert "validacao deterministica de filtros" in feedback
    assert "Category 2" in feedback
    assert "produziu ['2']" in feedback
    assert "Gere novamente o JSON completo" in feedback
    assert "remova filtros inventados" in feedback


@pytest.mark.parametrize(
    ("question", "filter_spec"),
    [
        (
            "Qual foi o ticket médio da Category 2 em fevereiro de 2025?",
            SalesFilter(SalesFilterField.CATEGORY, ("2",)),
        ),
        (
            "Calcule em fevereiro de 2025 o ticket médio para a Category 2.",
            SalesFilter(SalesFilterField.CATEGORY, ("2",)),
        ),
        (
            "Quais foram os três clientes que compraram mais unidades em 2025?",
            SalesFilter(SalesFilterField.CUSTOMER, ("all",)),
        ),
        (
            "Liste os três clientes líderes em unidades durante 2025.",
            SalesFilter(SalesFilterField.CUSTOMER, ("todos",)),
        ),
        (
            "Para a Category 1 em 2025, informe todas as métricas de vendas.",
            SalesFilter(SalesFilterField.CATEGORY, ("1",)),
        ),
        (
            "Resuma receita, vendas, unidades e ticket da Category 1 em 2025.",
            SalesFilter(SalesFilterField.CATEGORY, ("1",)),
        ),
        (
            "Para a Category 1, compare fevereiro de 2025 com janeiro de 2025.",
            SalesFilter(SalesFilterField.CATEGORY, ("1",)),
        ),
        (
            "Compare janeiro e fevereiro de 2025 somente para a Category 1.",
            SalesFilter(SalesFilterField.CATEGORY, ("1",)),
        ),
    ],
)
def test_filter_validator_rejects_the_failed_questions_and_paraphrases(
    question: str,
    filter_spec: SalesFilter,
) -> None:
    plan = SalesQueryPlan(
        queries=(AggregateSales(metrics=(SalesMetric.REVENUE,), filters=(filter_spec,)),)
    )

    with pytest.raises(PlannerFilterValidationError):
        validate_question_filter_constraints(question, plan)


def test_filter_validator_accepts_exact_literals_including_multiple_values() -> None:
    exact_category = SalesQueryPlan(
        queries=(
            AggregateSales(
                metrics=(SalesMetric.AVERAGE_TICKET,),
                filters=(SalesFilter(SalesFilterField.CATEGORY, ("Category 2",)),),
            ),
        )
    )
    selected_products = SalesQueryPlan(
        queries=(
            AggregateSales(
                metrics=(SalesMetric.REVENUE,),
                filters=(
                    SalesFilter(
                        SalesFilterField.PRODUCT,
                        ("Product A", "Product C", "Product E"),
                        FilterOperator.IN,
                    ),
                ),
            ),
        )
    )

    validate_question_filter_constraints(
        "Qual foi o ticket médio da Category 2?", exact_category
    )
    validate_question_filter_constraints(
        "Qual foi o ticket médio da Categoria 2?", exact_category
    )
    validate_question_filter_constraints(
        "Mostre Product A, Product C e Product E.", selected_products
    )
    validate_question_filter_constraints(
        "Quais clientes compraram mais unidades?",
        SalesQueryPlan(
            queries=(
                AggregateSales(
                    metrics=(SalesMetric.UNITS_SOLD,),
                    dimensions=(SalesDimension.CUSTOMER,),
                ),
            )
        ),
    )


def test_filter_validator_rejects_a_structured_literal_on_the_wrong_field() -> None:
    plan = SalesQueryPlan(
        queries=(
            AggregateSales(
                metrics=(SalesMetric.REVENUE,),
                filters=(SalesFilter(SalesFilterField.CATEGORY, ("SKU005",)),),
            ),
        )
    )

    with pytest.raises(PlannerFilterValidationError, match=r"pertence a \[product\]"):
        validate_question_filter_constraints("Receita do produto SKU005", plan)


def test_planner_deterministically_canonicalizes_a_structured_filter_literal() -> None:
    invalid_response = """{
        "calls": [{
            "operation": "sales.aggregate",
            "metrics": ["average_ticket"],
            "filters": [{"field": "category", "values": ["2"]}]
        }]
    }"""
    planner = LangChainSalesQueryPlanner(
        FakeListChatModel(responses=[invalid_response]),
        max_attempts=1,
        max_filter_validation_retries=0,
    )

    plan = planner.plan(question="Qual foi o ticket médio da Category 2?")

    query = plan.queries[0]
    assert isinstance(query, AggregateSales)
    assert query.filters == (
        SalesFilter(SalesFilterField.CATEGORY, ("Category 2",)),
    )


def test_planner_deterministically_preserves_multiple_structured_literals() -> None:
    response = """{
        "calls": [{
            "operation": "sales.aggregate",
            "metrics": ["revenue", "units_sold"],
            "dimensions": ["product"],
            "filters": [{"field": "product", "values": ["A"]}],
            "period": {
                "start": "2025-01-01T00:00:00Z",
                "end": "2025-12-31T23:59:59.999999Z"
            }
        }]
    }"""
    planner = LangChainSalesQueryPlanner(
        FakeListChatModel(responses=[response]),
        max_attempts=1,
        max_filter_validation_retries=0,
    )

    plan = planner.plan(
        question=(
            "Mostre receita e unidades vendidas por produto em 2025 apenas para "
            "Product A, Product C e Product E."
        )
    )

    query = plan.queries[0]
    assert isinstance(query, AggregateSales)
    assert query.filters == (
        SalesFilter(
            SalesFilterField.PRODUCT,
            ("Product A", "Product C", "Product E"),
            FilterOperator.IN,
        ),
    )


def test_planner_stops_after_the_configured_filter_retry_limit() -> None:
    invalid_response = """{
        "calls": [{
            "operation": "sales.aggregate",
            "metrics": ["units_sold"],
            "dimensions": ["customer"],
            "filters": [{"field": "customer", "values": ["all"]}],
            "sort": [{"metric": "units_sold"}],
            "limit": 3
        }]
    }"""
    model = FakeListChatModel(responses=[invalid_response] * 4)
    planner = LangChainSalesQueryPlanner(
        model,
        max_attempts=1,
        max_filter_validation_retries=2,
    )

    with pytest.raises(
        LangChainPlanningError,
        match=r"retries de filtro usados: 2/2",
    ):
        planner.plan(question="Quais clientes compraram mais unidades?")

    assert model.i == 3


@pytest.mark.parametrize(
    "operation",
    ["sales.calculate", "sales.top_products", "sales.basket", "sales.forecast"],
)
def test_planner_rejects_operations_outside_the_bounded_catalog(operation: str) -> None:
    planner = LangChainSalesQueryPlanner(
        FakeListChatModel(responses=[f'{{"calls":[{{"operation":"{operation}"}}]}}']),
        max_attempts=1,
    )

    with pytest.raises(LangChainPlanningError):
        planner.plan(question="Execute uma operacao fora do catalogo")


def test_query_contract_rejects_invalid_combinations() -> None:
    with pytest.raises(ValueError, match="limit exige"):
        AggregateSales(metrics=(SalesMetric.REVENUE,), limit=1)
    with pytest.raises(ValueError, match="no maximo uma"):
        SalesQueryPlan(
            queries=(
                AggregateSales(metrics=(SalesMetric.REVENUE,)),
                AggregateSales(metrics=(SalesMetric.SALE_COUNT,)),
            )
        )


def test_repository_aggregates_fundamental_metrics_in_database(
    relational_persistence: SqlAlchemyRelationalPersistence,
) -> None:
    query = AggregateSales(
        metrics=(
            SalesMetric.REVENUE,
            SalesMetric.SALE_COUNT,
            SalesMetric.UNITS_SOLD,
            SalesMetric.AVERAGE_TICKET,
        )
    )

    evidence = RepositorySalesQueryExecutor(relational_persistence).execute(
        plan=SalesQueryPlan(queries=(query,))
    )

    assert evidence.results == (
        RepositoryQueryResult(
            query=query,
            records=(
                SalesAnalysisResult(
                    rows=(
                        AnalysisRow(
                            metrics=(
                                AnalysisCell("revenue", Decimal("500.00")),
                                AnalysisCell("sale_count", 3),
                                AnalysisCell("units_sold", 6),
                                AnalysisCell("average_ticket", Decimal("166.67")),
                            )
                        ),
                    )
                ),
            ),
        ),
    )


def test_repository_groups_sorts_and_limits_by_week(
    relational_persistence: SqlAlchemyRelationalPersistence,
) -> None:
    query = AggregateSales(
        metrics=(SalesMetric.REVENUE,),
        dimensions=(SalesDimension.WEEK,),
        period=_period(2026),
        sort=(SortSpec(SalesMetric.REVENUE),),
        limit=1,
    )

    result = RepositorySalesQueryExecutor(relational_persistence).execute(
        plan=SalesQueryPlan(queries=(query,))
    )

    assert result.results[0].records == (
        SalesAnalysisResult(
            rows=(
                AnalysisRow(
                    dimensions=(AnalysisCell("week", "2026-W11"),),
                    metrics=(AnalysisCell("revenue", Decimal("300.00")),),
                ),
            )
        ),
    )


def test_repository_supports_product_filters_and_dimensions(
    relational_persistence: SqlAlchemyRelationalPersistence,
) -> None:
    query = AggregateSales(
        metrics=(SalesMetric.REVENUE, SalesMetric.UNITS_SOLD),
        dimensions=(SalesDimension.PRODUCT,),
        filters=(SalesFilter(SalesFilterField.PRODUCT, ("Furadeira",)),),
    )

    result = RepositorySalesQueryExecutor(relational_persistence).execute(
        plan=SalesQueryPlan(queries=(query,))
    )

    assert result.results[0].records == (
        SalesAnalysisResult(
            rows=(
                AnalysisRow(
                    dimensions=(AnalysisCell("product", "Furadeira"),),
                    metrics=(
                        AnalysisCell("revenue", Decimal("420.00")),
                        AnalysisCell("units_sold", 5),
                    ),
                ),
            )
        ),
    )


def test_repository_groups_by_category_and_customer(
    relational_persistence: SqlAlchemyRelationalPersistence,
) -> None:
    category_query = AggregateSales(
        metrics=(SalesMetric.REVENUE,),
        dimensions=(SalesDimension.CATEGORY,),
        sort=(SortSpec(SalesMetric.REVENUE),),
    )
    customer_query = AggregateSales(
        metrics=(SalesMetric.REVENUE,),
        dimensions=(SalesDimension.CUSTOMER,),
        sort=(SortSpec(SalesMetric.REVENUE),),
    )
    executor = RepositorySalesQueryExecutor(relational_persistence)

    categories = executor.execute(plan=SalesQueryPlan(queries=(category_query,)))
    customers = executor.execute(plan=SalesQueryPlan(queries=(customer_query,)))

    category_result = categories.results[0].records[0]
    customer_result = customers.results[0].records[0]
    assert isinstance(category_result, SalesAnalysisResult)
    assert isinstance(customer_result, SalesAnalysisResult)
    assert [row.dimension_key() for row in category_result.rows] == [
        ("Ferramentas",),
        ("Acabamento",),
    ]
    assert [row.metric_value("revenue") for row in category_result.rows] == [
        Decimal("420.00"),
        Decimal("80.00"),
    ]
    assert [row.dimension_key() for row in customer_result.rows] == [
        ("Bruno Reis",),
        ("Ana Lima",),
    ]
    assert [row.metric_value("revenue") for row in customer_result.rows] == [
        Decimal("300.00"),
        Decimal("200.00"),
    ]


def test_executor_compares_periods_deterministically(
    relational_persistence: SqlAlchemyRelationalPersistence,
) -> None:
    query = CompareSales(
        metrics=(SalesMetric.REVENUE,),
        current_period=TimePeriod(
            datetime(2026, 3, 1, tzinfo=UTC),
            datetime(2026, 3, 31, 23, 59, 59, 999999, tzinfo=UTC),
        ),
        baseline_period=TimePeriod(
            datetime(2026, 1, 1, tzinfo=UTC),
            datetime(2026, 1, 31, 23, 59, 59, 999999, tzinfo=UTC),
        ),
    )

    result = RepositorySalesQueryExecutor(relational_persistence).execute(
        plan=SalesQueryPlan(queries=(query,))
    )

    assert result.results[0].records == (
        SalesAnalysisResult(
            rows=(
                AnalysisRow(
                    metrics=(
                        AnalysisCell("revenue.current", Decimal("300.00")),
                        AnalysisCell("revenue.baseline", Decimal("120.00")),
                        AnalysisCell("revenue.absolute_change", Decimal("180.00")),
                        AnalysisCell("revenue.percentage_change", Decimal("150.0000")),
                    )
                ),
            )
        ),
    )


def test_get_sales_insights_formats_weekly_ranking(
    relational_persistence: SqlAlchemyRelationalPersistence,
) -> None:
    planner = LangChainSalesQueryPlanner(
        FakeListChatModel(
            responses=[
                """{
                    "calls": [{
                        "operation": "sales.aggregate",
                        "metrics": ["revenue"],
                        "dimensions": ["week"],
                        "period": {
                            "start": "2026-01-01T00:00:00Z",
                            "end": "2026-12-31T23:59:59.999999Z"
                        },
                        "sort": [{"metric": "revenue"}],
                        "limit": 1
                    }]
                }"""
            ]
        )
    )
    use_case = GetSalesInsightsUseCase(
        planner=planner,
        query_executor=RepositorySalesQueryExecutor(relational_persistence),
        synthesizer=DeterministicSalesInsightSynthesizer(),
    )

    result = use_case.execute(question="Qual foi a semana de 2026 que mais vendeu?")

    assert result.answer == ("A semana com maior receita em 2026 foi 2026-W11, com R$ 300,00.")
    assert result.plan is not None
    assert result.plan.queries[0].dimensions == (SalesDimension.WEEK,)


def test_seeded_2025_revenue_regression_is_calculated_exactly(tmp_path: Path) -> None:
    database_url = f"sqlite+pysqlite:///{(tmp_path / 'seeded.db').as_posix()}"
    upgrade_database(database_url)
    seed_database(database_url)
    persistence = SqlAlchemyRelationalPersistence(database_url)
    query = AggregateSales(metrics=(SalesMetric.REVENUE,), period=_period(2025))

    try:
        evidence = RepositorySalesQueryExecutor(persistence).execute(
            plan=SalesQueryPlan(queries=(query,))
        )
        answer = DeterministicSalesInsightSynthesizer().synthesize(
            question="Qual foi o total de vendas do ano de 2025?",
            evidence=evidence,
        )
    finally:
        persistence.dispose()

    dataset = evidence.results[0].records[0]
    assert isinstance(dataset, SalesAnalysisResult)
    assert dataset.rows[0].metric_value("revenue") == Decimal("2309.78")
    assert answer == "O total de vendas em 2025 foi de R$ 2.309,78."


def test_synthesizer_explains_the_supported_catalog_for_empty_plan() -> None:
    answer = DeterministicSalesInsightSynthesizer().synthesize(
        question="Explique por que as vendas cairam",
        evidence=SalesQueryEvidence(results=()),
    )

    assert "agrupamentos" in answer
    assert "comparações" in answer


def test_get_sales_insights_rejects_blank_questions_before_calling_dependencies() -> None:
    planner = LangChainSalesQueryPlanner(FakeListChatModel(responses=['{"calls":[]}']))

    class UnexpectedExecutor:
        def execute(
            self,
            *,
            plan: SalesQueryPlan,
            cursor: str | None = None,
        ) -> SalesQueryEvidence:
            del plan, cursor
            raise AssertionError("executor nao deveria ser chamado")

    use_case = GetSalesInsightsUseCase(
        planner=planner,
        query_executor=UnexpectedExecutor(),
        synthesizer=DeterministicSalesInsightSynthesizer(),
    )

    with pytest.raises(ValueError, match="vazia"):
        use_case.execute(question="   ")
