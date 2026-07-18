"""Carrega explicitamente o dataset de referencia no banco configurado."""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy import Connection
    from sqlalchemy.engine import URL

ROOT = Path(__file__).resolve().parents[1]
VENV_PYTHON = (
    ROOT / ".venv" / "Scripts" / "python.exe"
    if sys.platform == "win32"
    else ROOT / ".venv" / "bin" / "python"
)

PRODUCTS = (
    ("SKU001", "Product A", "Category 1", Decimal("10.99")),
    ("SKU002", "Product B", "Category 1", Decimal("20.50")),
    ("SKU003", "Product C", "Category 2", Decimal("15.75")),
    ("SKU004", "Product D", "Category 3", Decimal("30.00")),
    ("SKU005", "Product E", "Category 4", Decimal("25.00")),
)

CUSTOMERS = (
    ("John Doe", "john@example.com"),
    ("Jane Smith", "jane@example.com"),
    ("Bob Johnson", "bob@example.com"),
    ("Alice Brown", "alice@example.com"),
    ("Charlie Davis", "charlie@example.com"),
)

SALES = (
    (4, 1, 4, "120.00", "2025-01-17 12:22:49"),
    (5, 1, 7, "175.00", "2025-01-28 04:04:17"),
    (5, 4, 4, "100.00", "2025-02-04 11:58:16"),
    (1, 2, 2, "21.98", "2025-01-05 10:30:45"),
    (2, 3, 1, "20.50", "2025-01-06 15:15:10"),
    (3, 5, 3, "47.25", "2025-01-08 09:45:22"),
    (4, 2, 1, "30.00", "2025-01-10 17:22:30"),
    (5, 4, 5, "125.00", "2025-01-12 11:00:00"),
    (1, 3, 2, "21.98", "2025-01-14 18:25:45"),
    (2, 5, 6, "123.00", "2025-01-15 13:12:22"),
    (3, 1, 2, "31.50", "2025-01-18 08:10:33"),
    (4, 4, 1, "30.00", "2025-01-20 14:05:20"),
    (5, 2, 3, "75.00", "2025-01-23 19:30:40"),
    (1, 5, 2, "21.98", "2025-01-25 10:45:10"),
    (2, 4, 4, "82.00", "2025-01-29 16:20:50"),
    (3, 2, 1, "15.75", "2025-02-01 12:00:00"),
    (4, 5, 2, "60.00", "2025-02-03 18:40:30"),
    (5, 1, 8, "200.00", "2025-02-05 11:25:00"),
    (1, 4, 3, "32.97", "2025-02-07 14:50:10"),
    (2, 3, 2, "41.00", "2025-02-08 10:20:15"),
    (3, 5, 4, "63.00", "2025-02-10 16:45:55"),
    (4, 2, 1, "30.00", "2025-02-12 20:30:00"),
    (5, 3, 2, "50.00", "2025-02-15 09:10:10"),
    (1, 1, 6, "65.94", "2025-02-16 13:35:30"),
    (2, 4, 2, "41.00", "2025-02-18 15:00:00"),
    (3, 2, 3, "47.25", "2025-02-19 11:30:45"),
    (4, 5, 2, "60.00", "2025-02-21 14:10:22"),
    (5, 4, 1, "25.00", "2025-02-22 19:45:55"),
    (1, 2, 7, "76.93", "2025-02-24 12:10:10"),
    (2, 1, 4, "82.00", "2025-02-25 17:30:50"),
    (3, 3, 5, "78.75", "2025-02-27 09:55:00"),
    (4, 5, 3, "90.00", "2025-02-28 14:25:30"),
    (5, 2, 9, "225.00", "2025-03-02 10:00:00"),
)


def _seed(connection: Connection) -> None:
    import sqlalchemy as sa

    required_tables = {"products", "customers", "sales"}
    existing_tables = set(sa.inspect(connection).get_table_names())
    missing_tables = required_tables - existing_tables
    if missing_tables:
        missing = ", ".join(sorted(missing_tables))
        raise RuntimeError(f"schema relacional ausente; execute as migracoes primeiro: {missing}")

    metadata = sa.MetaData()
    products = sa.Table("products", metadata, autoload_with=connection)
    customers = sa.Table("customers", metadata, autoload_with=connection)
    sales = sa.Table("sales", metadata, autoload_with=connection)

    existing_skus = set(connection.scalars(sa.select(products.c.sku)))
    missing_products = [
        {
            "sku": sku,
            "name": name,
            "category": category,
            "price": price,
            "active": True,
        }
        for sku, name, category, price in PRODUCTS
        if sku not in existing_skus
    ]
    if missing_products:
        connection.execute(products.insert(), missing_products)

    existing_emails = set(connection.scalars(sa.select(customers.c.email)))
    missing_customers = [
        {"name": name, "email": email} for name, email in CUSTOMERS if email not in existing_emails
    ]
    if missing_customers:
        connection.execute(customers.insert(), missing_customers)

    product_ids = {
        sku: product_id
        for sku, product_id in connection.execute(sa.select(products.c.sku, products.c.id))
    }
    customer_ids = {
        email: customer_id
        for email, customer_id in connection.execute(sa.select(customers.c.email, customers.c.id))
    }
    existing_sales = {
        tuple(row)
        for row in connection.execute(
            sa.select(
                sales.c.product_id,
                sales.c.customer_id,
                sales.c.quantity,
                sales.c.total_amount,
                sales.c.sale_date,
            )
        )
    }
    missing_sales: list[dict[str, object]] = []
    for product_number, customer_number, quantity, total_amount, sale_date in SALES:
        row = {
            "product_id": product_ids[PRODUCTS[product_number - 1][0]],
            "customer_id": customer_ids[CUSTOMERS[customer_number - 1][1]],
            "quantity": quantity,
            "total_amount": Decimal(total_amount),
            "sale_date": datetime.fromisoformat(sale_date),
        }
        signature = tuple(row[column] for column in row)
        if signature not in existing_sales:
            missing_sales.append(row)
    if missing_sales:
        connection.execute(sales.insert(), missing_sales)


def seed_database(database_url: str | URL) -> None:
    """Load the reference dataset without changing migration state."""

    import sqlalchemy as sa

    engine = sa.create_engine(database_url)
    try:
        with engine.begin() as connection:
            _seed(connection)
    finally:
        engine.dispose()


def _run_seed() -> int:
    from sqlalchemy.engine import make_url

    from garage_sales.config import RelationalDatabaseSettings, load_runtime_env

    load_runtime_env()
    settings = RelationalDatabaseSettings.from_env()
    seed_database(settings.url)
    dialect = make_url(settings.url).get_backend_name()
    print(f"Seeds aplicados: {dialect}")
    return 0


def main() -> int:
    if Path(sys.executable).resolve() == VENV_PYTHON.resolve():
        return _run_seed()

    if not VENV_PYTHON.exists():
        print("Ambiente ausente. Execute: python scripts/bootstrap.py", file=sys.stderr)
        return 2

    completed = subprocess.run(
        [str(VENV_PYTHON), str(Path(__file__).resolve())],
        cwd=ROOT,
        check=False,
    )
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
