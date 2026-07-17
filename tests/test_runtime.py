from pathlib import Path

from fastapi.testclient import TestClient
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from sqlalchemy import create_engine, inspect

from garage_sales.config import RelationalDatabaseSettings
from garage_sales.runtime import create_runtime_app


def test_runtime_composition_connects_langchain_use_case_to_http(tmp_path: Path) -> None:
    database_path = (tmp_path / "runtime.db").as_posix()
    model = FakeListChatModel(
        responses=[
            """{
                "calls": [{
                    "operation": "sales.aggregate",
                    "metrics": ["revenue"],
                    "dimensions": ["year"],
                    "filters": [{"field": "year", "values": ["2025"]}],
                    "period": {
                        "start": "2025-01-01T00:00:00Z",
                        "end": "2026-01-01T00:00:00Z"
                    }
                }]
            }"""
        ]
    )
    app = create_runtime_app(
        database_settings=RelationalDatabaseSettings(url=f"sqlite+pysqlite:///{database_path}"),
        model=model,
    )

    with TestClient(app) as client:
        response = client.get(
            "/sales-insights",
            params={"question": "Qual foi o total de vendas do ano de 2025"},
        )

    assert response.status_code == 200
    assert "R$ 2.309,78" in response.json()["answer"]
    engine = create_engine(f"sqlite+pysqlite:///{database_path}")
    try:
        assert {"orders", "order_items"} <= set(inspect(engine).get_table_names())
    finally:
        engine.dispose()
