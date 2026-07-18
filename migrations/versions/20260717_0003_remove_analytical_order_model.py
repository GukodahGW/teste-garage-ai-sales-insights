"""Remove the retired order-based analytics schema from existing databases.

Revision ID: 20260717_0003
Revises: 20260717_0002
Create Date: 2026-07-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260717_0003"
down_revision: str | None = "20260717_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    tables = set(inspector.get_table_names())

    for table_name in ("refunds", "order_items", "orders"):
        if table_name in tables:
            op.drop_table(table_name)

    inspector = sa.inspect(connection)
    product_columns = {column["name"] for column in inspector.get_columns("products")}
    if "category_id" in product_columns:
        product_indexes = {index["name"] for index in inspector.get_indexes("products")}
        product_foreign_keys = {
            foreign_key["name"]
            for foreign_key in inspector.get_foreign_keys("products")
            if foreign_key["name"] is not None
        }
        with op.batch_alter_table("products") as batch:
            if "ix_products_category_id" in product_indexes:
                batch.drop_index("ix_products_category_id")
            if "fk_products_category_id_categories" in product_foreign_keys:
                batch.drop_constraint("fk_products_category_id_categories", type_="foreignkey")
            batch.drop_column("category_id")

    if "categories" in tables:
        op.drop_table("categories")


def downgrade() -> None:
    # Recreate the retired revision's structure so Alembic can continue through
    # revision 0002 when a caller explicitly downgrades farther. Data written only
    # to the retired tables cannot be reconstructed after their removal.
    op.create_table(
        "categories",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_categories")),
        sa.UniqueConstraint("name", name=op.f("uq_categories_name")),
    )
    op.create_index(op.f("ix_categories_name"), "categories", ["name"], unique=True)

    with op.batch_alter_table("products") as batch:
        batch.add_column(sa.Column("category_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            op.f("fk_products_category_id_categories"),
            "categories",
            ["category_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch.create_index(op.f("ix_products_category_id"), ["category_id"], unique=False)

    op.create_table(
        "orders",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=True),
        sa.Column("ordered_at", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(length=30), server_default="completed", nullable=False),
        sa.Column("currency", sa.String(length=3), server_default="BRL", nullable=False),
        sa.Column("gross_amount", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column(
            "discount_amount",
            sa.Numeric(precision=14, scale=2),
            server_default="0.00",
            nullable=False,
        ),
        sa.Column("net_amount", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("legacy_sale_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["customer_id"],
            ["customers.id"],
            name=op.f("fk_orders_customer_id_customers"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["legacy_sale_id"],
            ["sales.id"],
            name=op.f("fk_orders_legacy_sale_id_sales"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_orders")),
        sa.UniqueConstraint("legacy_sale_id", name=op.f("uq_orders_legacy_sale_id")),
    )
    for column in ("customer_id", "ordered_at", "status", "currency"):
        op.create_index(op.f(f"ix_orders_{column}"), "orders", [column], unique=False)

    op.create_table(
        "order_items",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=True),
        sa.Column("quantity", sa.Integer(), server_default="1", nullable=False),
        sa.Column("unit_price", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column(
            "discount_amount",
            sa.Numeric(precision=14, scale=2),
            server_default="0.00",
            nullable=False,
        ),
        sa.Column("net_amount", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("product_sku", sa.String(length=50), nullable=True),
        sa.Column("product_name", sa.String(length=255), nullable=True),
        sa.Column("category_name", sa.String(length=100), nullable=True),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["orders.id"],
            name=op.f("fk_order_items_order_id_orders"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name=op.f("fk_order_items_product_id_products"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_order_items")),
    )
    for column in ("order_id", "product_id", "category_name"):
        op.create_index(op.f(f"ix_order_items_{column}"), "order_items", [column], unique=False)

    op.create_table(
        "refunds",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("order_item_id", sa.Integer(), nullable=True),
        sa.Column("amount", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("refunded_at", sa.DateTime(), nullable=False),
        sa.Column("reason", sa.String(length=255), nullable=True),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["orders.id"],
            name=op.f("fk_refunds_order_id_orders"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["order_item_id"],
            ["order_items.id"],
            name=op.f("fk_refunds_order_item_id_order_items"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_refunds")),
    )
    for column in ("order_id", "order_item_id", "refunded_at"):
        op.create_index(op.f(f"ix_refunds_{column}"), "refunds", [column], unique=False)
