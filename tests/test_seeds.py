import os
import subprocess
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select

from garage_sales.infrastructure.sqlalchemy.migrations import upgrade_database
from garage_sales.infrastructure.sqlalchemy.models import (
    CustomerModel,
    ProductModel,
    SaleModel,
)
from scripts.seed import seed_database

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _database_url(path: Path) -> str:
    return f"sqlite+pysqlite:///{path.as_posix()}"


def test_seed_is_explicit_and_idempotent(tmp_path: Path) -> None:
    database_url = _database_url(tmp_path / "seed.db")
    upgrade_database(database_url)

    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            assert connection.scalar(select(func.count()).select_from(SaleModel)) == 0
    finally:
        engine.dispose()

    seed_database(database_url)
    seed_database(database_url)

    seeded_engine = create_engine(database_url)
    try:
        with seeded_engine.connect() as connection:
            assert connection.scalar(select(func.count()).select_from(ProductModel)) == 5
            assert connection.scalar(select(func.count()).select_from(CustomerModel)) == 5
            assert connection.scalar(select(func.count()).select_from(SaleModel)) == 33

            product = connection.execute(
                select(ProductModel.sku, ProductModel.category, ProductModel.unit_price).where(
                    ProductModel.sku == "SKU001"
                )
            ).one()
            assert tuple(product) == ("SKU001", "Category 1", Decimal("10.99"))

            last_sale = connection.execute(
                select(SaleModel.product_id, SaleModel.customer_id, SaleModel.quantity).where(
                    SaleModel.sold_at == datetime(2025, 3, 2, 10)
                )
            ).one()
            assert tuple(last_sale) == (5, 2, 9)
    finally:
        seeded_engine.dispose()


def test_seed_requires_the_schema_to_be_migrated(tmp_path: Path) -> None:
    database_url = _database_url(tmp_path / "missing-schema.db")

    with pytest.raises(RuntimeError, match="execute as migracoes primeiro"):
        seed_database(database_url)


def test_seed_script_uses_the_active_database_url(tmp_path: Path) -> None:
    database_url = _database_url(tmp_path / "script.db")
    upgrade_database(database_url)
    environment = os.environ.copy()
    environment["GARAGE_DATABASE_URL"] = database_url

    completed = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "scripts" / "seed.py")],
        cwd=PROJECT_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert "Seeds aplicados: sqlite" in completed.stdout

    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            assert connection.scalar(select(func.count()).select_from(SaleModel)) == 33
    finally:
        engine.dispose()
