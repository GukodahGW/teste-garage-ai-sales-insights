"""Create the initial sales schema and load the reference dataset.

Revision ID: 20260717_0001
Revises:
Create Date: 2026-07-17
"""

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal

import sqlalchemy as sa
from alembic import op

revision: str = "20260717_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

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


def _create_schema() -> None:
    op.create_table(
        "products",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("sku", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("category", sa.String(length=100), nullable=True),
        sa.Column("price", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_products")),
        sa.UniqueConstraint("sku", name=op.f("uq_products_sku")),
    )
    op.create_index(op.f("ix_products_name"), "products", ["name"], unique=False)
    op.create_index(op.f("ix_products_active"), "products", ["active"], unique=False)

    op.create_table(
        "customers",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.func.current_timestamp(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_customers")),
        sa.UniqueConstraint("email", name=op.f("uq_customers_email")),
    )
    op.create_index(op.f("ix_customers_name"), "customers", ["name"], unique=False)

    op.create_table(
        "sales",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=True),
        sa.Column("customer_id", sa.Integer(), nullable=True),
        sa.Column("quantity", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("total_amount", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("sale_date", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["customer_id"],
            ["customers.id"],
            name=op.f("fk_sales_customer_id_customers"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name=op.f("fk_sales_product_id_products"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sales")),
    )
    op.create_index(op.f("ix_sales_product_id"), "sales", ["product_id"], unique=False)
    op.create_index(op.f("ix_sales_customer_id"), "sales", ["customer_id"], unique=False)
    op.create_index(op.f("ix_sales_sale_date"), "sales", ["sale_date"], unique=False)


def _batch_recreate_mode(connection: sa.Connection) -> str:
    return "always" if connection.dialect.name == "sqlite" else "auto"


def _upgrade_existing_schema(connection: sa.Connection) -> None:
    inspector = sa.inspect(connection)
    recreate = _batch_recreate_mode(connection)

    product_column_definitions = {
        column["name"]: column for column in inspector.get_columns("products")
    }
    product_columns = set(product_column_definitions)
    with op.batch_alter_table("products", recreate=recreate) as batch:
        if "unit_price" in product_columns and "price" not in product_columns:
            batch.alter_column(
                "unit_price",
                new_column_name="price",
                existing_type=sa.Numeric(precision=14, scale=2),
                type_=sa.Numeric(precision=10, scale=2),
                existing_nullable=False,
                nullable=True,
            )
        elif "price" not in product_columns:
            batch.add_column(sa.Column("price", sa.Numeric(precision=10, scale=2), nullable=True))
        if "category" not in product_columns:
            batch.add_column(sa.Column("category", sa.String(length=100), nullable=True))
        if "active" not in product_columns:
            batch.add_column(
                sa.Column("active", sa.Boolean(), server_default=sa.true(), nullable=False)
            )
        elif product_column_definitions["active"]["default"] is None:
            batch.alter_column(
                "active",
                existing_type=sa.Boolean(),
                existing_nullable=False,
                server_default=sa.true(),
            )

    customer_columns = {column["name"] for column in inspector.get_columns("customers")}
    if "created_at" not in customer_columns:
        with op.batch_alter_table("customers", recreate=recreate) as batch:
            batch.add_column(
                sa.Column(
                    "created_at",
                    sa.DateTime(),
                    server_default=sa.func.current_timestamp(),
                    nullable=False,
                )
            )

    sale_columns = {column["name"] for column in inspector.get_columns("sales")}
    foreign_keys = {
        tuple(foreign_key["constrained_columns"])
        for foreign_key in inspector.get_foreign_keys("sales")
    }
    with op.batch_alter_table("sales", recreate=recreate) as batch:
        if "sold_at" in sale_columns and "sale_date" not in sale_columns:
            batch.alter_column(
                "sold_at",
                new_column_name="sale_date",
                existing_type=sa.DateTime(),
                type_=sa.DateTime(),
                existing_nullable=False,
            )
        elif "sale_date" not in sale_columns:
            batch.add_column(sa.Column("sale_date", sa.DateTime(), nullable=True))
        if "product_id" not in sale_columns:
            batch.add_column(sa.Column("product_id", sa.Integer(), nullable=True))
        if "quantity" not in sale_columns:
            batch.add_column(
                sa.Column(
                    "quantity",
                    sa.Integer(),
                    server_default=sa.text("1"),
                    nullable=False,
                )
            )
        if ("product_id",) not in foreign_keys:
            batch.create_foreign_key(
                op.f("fk_sales_product_id_products"),
                "products",
                ["product_id"],
                ["id"],
                ondelete="RESTRICT",
            )

    refreshed_inspector = sa.inspect(connection)
    indexes = {
        table_name: {index["name"] for index in refreshed_inspector.get_indexes(table_name)}
        for table_name in ("products", "customers", "sales")
    }
    expected_indexes = (
        ("products", "ix_products_name", ["name"]),
        ("products", "ix_products_active", ["active"]),
        ("customers", "ix_customers_name", ["name"]),
        ("sales", "ix_sales_product_id", ["product_id"]),
        ("sales", "ix_sales_customer_id", ["customer_id"]),
        ("sales", "ix_sales_sale_date", ["sale_date"]),
    )
    for table_name, index_name, columns in expected_indexes:
        if index_name not in indexes[table_name]:
            op.create_index(op.f(index_name), table_name, columns, unique=False)


def _seed(connection: sa.Connection) -> None:
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
        op.bulk_insert(products, missing_products)

    existing_emails = set(connection.scalars(sa.select(customers.c.email)))
    missing_customers = [
        {"name": name, "email": email} for name, email in CUSTOMERS if email not in existing_emails
    ]
    if missing_customers:
        op.bulk_insert(customers, missing_customers)

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
        op.bulk_insert(sales, missing_sales)


def upgrade() -> None:
    connection = op.get_bind()
    managed_tables = {"products", "customers", "sales"}
    existing_tables = set(sa.inspect(connection).get_table_names())
    present_managed_tables = managed_tables & existing_tables

    if not present_managed_tables:
        _create_schema()
    elif present_managed_tables == managed_tables:
        _upgrade_existing_schema(connection)
    else:
        missing_tables = ", ".join(sorted(managed_tables - present_managed_tables))
        raise RuntimeError(f"schema relacional incompleto; tabelas ausentes: {missing_tables}")

    _seed(connection)


def downgrade() -> None:
    op.drop_table("sales")
    op.drop_table("customers")
    op.drop_table("products")
