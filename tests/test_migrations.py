import os
import subprocess
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    MetaData,
    Numeric,
    String,
    Table,
    create_engine,
    func,
    inspect,
    select,
)

from garage_sales.infrastructure.sqlalchemy.migrations import (
    downgrade_database,
    upgrade_database,
)
from garage_sales.infrastructure.sqlalchemy.models import (
    CustomerModel,
    ProductModel,
    SaleModel,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _database_url(path: Path) -> str:
    return f"sqlite+pysqlite:///{path.as_posix()}"


def _create_legacy_schema(database_url: str) -> None:
    metadata = MetaData()
    products = Table(
        "products",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("sku", String(64), unique=True, nullable=False),
        Column("name", String(200), index=True, nullable=False),
        Column("unit_price", Numeric(14, 2), nullable=False),
        Column("active", Boolean, index=True, nullable=False),
    )
    customers = Table(
        "customers",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("name", String(160), index=True, nullable=False),
        Column("email", String(320), unique=True, nullable=False),
    )
    sales = Table(
        "sales",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("customer_id", ForeignKey("customers.id"), index=True, nullable=False),
        Column("total_amount", Numeric(14, 2), nullable=False),
        Column("sold_at", DateTime, index=True, nullable=False),
    )
    engine = create_engine(database_url)
    try:
        metadata.create_all(engine)
        with engine.begin() as connection:
            connection.execute(
                products.insert(),
                {
                    "sku": "LEGACY-001",
                    "name": "Legacy product",
                    "unit_price": Decimal("99.90"),
                    "active": True,
                },
            )
            customer_id = connection.execute(
                customers.insert().returning(customers.c.id),
                {"name": "Legacy customer", "email": "legacy@example.com"},
            ).scalar_one()
            connection.execute(
                sales.insert(),
                {
                    "customer_id": customer_id,
                    "total_amount": Decimal("99.90"),
                    "sold_at": datetime(2024, 12, 31, 12),
                },
            )
    finally:
        engine.dispose()


def test_initial_migration_creates_schema_and_seeds_attached_dataset(tmp_path: Path) -> None:
    database_url = _database_url(tmp_path / "migration.db")

    upgrade_database(database_url)

    engine = create_engine(database_url)
    try:
        inspector = inspect(engine)
        assert {"alembic_version", "customers", "products", "sales"} <= set(
            inspector.get_table_names()
        )
        assert {column["name"] for column in inspector.get_columns("products")} >= {
            "id",
            "sku",
            "name",
            "category",
            "price",
        }
        assert {column["name"] for column in inspector.get_columns("customers")} >= {
            "id",
            "name",
            "email",
            "created_at",
        }
        assert {column["name"] for column in inspector.get_columns("sales")} == {
            "id",
            "product_id",
            "customer_id",
            "quantity",
            "total_amount",
            "sale_date",
        }

        with engine.connect() as connection:
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
        engine.dispose()


def test_migration_is_idempotent_and_can_be_downgraded(tmp_path: Path) -> None:
    database_url = _database_url(tmp_path / "idempotent.db")

    upgrade_database(database_url)
    upgrade_database(database_url)

    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            assert connection.scalar(select(func.count()).select_from(ProductModel)) == 5
            assert connection.scalar(select(func.count()).select_from(CustomerModel)) == 5
            assert connection.scalar(select(func.count()).select_from(SaleModel)) == 33
    finally:
        engine.dispose()

    downgrade_database(database_url, "base")

    downgraded_engine = create_engine(database_url)
    try:
        tables = set(inspect(downgraded_engine).get_table_names())
        assert "products" not in tables
        assert "customers" not in tables
        assert "sales" not in tables
    finally:
        downgraded_engine.dispose()


def test_initial_migration_upgrades_an_unversioned_legacy_schema_without_data_loss(
    tmp_path: Path,
) -> None:
    database_url = _database_url(tmp_path / "legacy.db")
    _create_legacy_schema(database_url)

    upgrade_database(database_url)

    engine = create_engine(database_url)
    try:
        inspector = inspect(engine)
        assert "unit_price" not in {column["name"] for column in inspector.get_columns("products")}
        assert "price" in {column["name"] for column in inspector.get_columns("products")}
        assert "sold_at" not in {column["name"] for column in inspector.get_columns("sales")}
        assert "sale_date" in {column["name"] for column in inspector.get_columns("sales")}

        with engine.connect() as connection:
            assert connection.scalar(select(func.count()).select_from(ProductModel)) == 6
            assert connection.scalar(select(func.count()).select_from(CustomerModel)) == 6
            assert connection.scalar(select(func.count()).select_from(SaleModel)) == 34

            legacy_product = connection.execute(
                select(ProductModel.unit_price, ProductModel.category).where(
                    ProductModel.sku == "LEGACY-001"
                )
            ).one()
            assert tuple(legacy_product) == (Decimal("99.90"), None)

            legacy_sale = connection.execute(
                select(SaleModel.product_id, SaleModel.quantity).where(
                    SaleModel.sold_at == datetime(2024, 12, 31, 12)
                )
            ).one()
            assert tuple(legacy_sale) == (None, 1)
    finally:
        engine.dispose()


def test_migration_script_uses_the_active_database_url(tmp_path: Path) -> None:
    database_url = _database_url(tmp_path / "script.db")
    environment = os.environ.copy()
    environment["GARAGE_DATABASE_URL"] = database_url

    completed = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "scripts" / "migrate.py")],
        cwd=PROJECT_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert "Migracoes aplicadas e seed validado: sqlite" in completed.stdout

    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            assert connection.scalar(select(func.count()).select_from(SaleModel)) == 33
    finally:
        engine.dispose()
