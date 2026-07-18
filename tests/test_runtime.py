from pathlib import Path

from fastapi.testclient import TestClient
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from sqlalchemy import create_engine, inspect

from garage_sales.config import RelationalDatabaseSettings, SalesQueryPlannerSettings
from garage_sales.infrastructure.sqlalchemy.migrations import upgrade_database
from garage_sales.runtime import create_runtime_app
from scripts.seed import seed_database


def test_runtime_composition_connects_langchain_use_case_to_http(tmp_path: Path) -> None:
    database_path = (tmp_path / "runtime.db").as_posix()
    database_url = f"sqlite+pysqlite:///{database_path}"
    upgrade_database(database_url)
    seed_database(database_url)
    model = FakeListChatModel(
        responses=[
            """{
                "calls": [{
                    "operation": "sales.aggregate",
                    "metrics": ["revenue"],
                    "period": {
                        "start": "2025-01-01T00:00:00Z",
                        "end": "2025-12-31T23:59:59.999999Z"
                    }
                }]
            }"""
        ]
    )
    app = create_runtime_app(
        database_settings=RelationalDatabaseSettings(url=database_url),
        model=model,
    )

    with TestClient(app) as client:
        response = client.get(
            "/sales-insights",
            params={"question": "Qual foi o total de vendas do ano de 2025"},
        )

    assert response.status_code == 200
    assert "R$ 2.309,78" in response.json()["answer"]
    engine = create_engine(database_url)
    try:
        assert set(inspect(engine).get_table_names()) == {
            "alembic_version",
            "customers",
            "products",
            "sales",
        }
    finally:
        engine.dispose()


def test_runtime_startup_does_not_run_migrations(tmp_path: Path) -> None:
    database_path = tmp_path / "unmigrated.db"
    app = create_runtime_app(
        database_settings=RelationalDatabaseSettings(
            url=f"sqlite+pysqlite:///{database_path.as_posix()}"
        ),
        model=FakeListChatModel(responses=[]),
    )

    with TestClient(app):
        pass

    assert not database_path.exists()


def test_runtime_applies_the_configured_date_validation_retry_limit(tmp_path: Path) -> None:
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
    model = FakeListChatModel(responses=[invalid_response] * 3)
    app = create_runtime_app(
        database_settings=RelationalDatabaseSettings(
            url=f"sqlite+pysqlite:///{(tmp_path / 'unused.db').as_posix()}"
        ),
        planner_settings=SalesQueryPlannerSettings(date_validation_max_retries=0),
        model=model,
    )

    with TestClient(app) as client:
        response = client.get(
            "/sales-insights",
            params={
                "question": "Compare a receita de fevereiro de 2025 com janeiro de 2025."
            },
        )

    assert response.status_code == 422
    assert "retries de data usados: 0/0" in response.json()["detail"]
    assert model.i == 1


def test_runtime_applies_the_configured_filter_validation_retry_limit(tmp_path: Path) -> None:
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
    model = FakeListChatModel(responses=[invalid_response] * 3)
    app = create_runtime_app(
        database_settings=RelationalDatabaseSettings(
            url=f"sqlite+pysqlite:///{(tmp_path / 'unused-filter.db').as_posix()}"
        ),
        planner_settings=SalesQueryPlannerSettings(filter_validation_max_retries=0),
        model=model,
    )

    with TestClient(app) as client:
        response = client.get(
            "/sales-insights",
            params={"question": "Quais clientes compraram mais unidades?"},
        )

    assert response.status_code == 422
    assert "retries de filtro usados: 0/0" in response.json()["detail"]
    assert model.i == 1
