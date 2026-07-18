"""Create the initial sales schema.

Revision ID: 20260717_0001
Revises:
Create Date: 2026-07-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260717_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


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


def downgrade() -> None:
    op.drop_table("sales")
    op.drop_table("customers")
    op.drop_table("products")
