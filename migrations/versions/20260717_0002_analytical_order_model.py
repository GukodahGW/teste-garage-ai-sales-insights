"""Add the order/item grain required by relational sales analytics.

Revision ID: 20260717_0002
Revises: 20260717_0001
Create Date: 2026-07-17
"""

from collections.abc import Sequence
from decimal import Decimal

import sqlalchemy as sa
from alembic import op

revision: str = "20260717_0002"
down_revision: str | None = "20260717_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _create_schema() -> None:
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


def _backfill(connection: sa.Connection) -> None:
    metadata = sa.MetaData()
    products = sa.Table("products", metadata, autoload_with=connection)
    categories = sa.Table("categories", metadata, autoload_with=connection)
    sales = sa.Table("sales", metadata, autoload_with=connection)
    orders = sa.Table("orders", metadata, autoload_with=connection)
    items = sa.Table("order_items", metadata, autoload_with=connection)

    category_names = [
        value
        for value in connection.scalars(
            sa.select(products.c.category).where(products.c.category.is_not(None)).distinct()
        )
        if value
    ]
    if category_names:
        connection.execute(
            categories.insert(),
            [{"name": category_name} for category_name in category_names],
        )
        category_ids = {
            row["name"]: row["id"]
            for row in connection.execute(sa.select(categories.c.name, categories.c.id)).mappings()
        }
        for category_name, category_id in category_ids.items():
            connection.execute(
                products.update()
                .where(products.c.category == category_name)
                .values(category_id=category_id)
            )

    product_snapshots = {
        product_id: (sku, name, category)
        for product_id, sku, name, category in connection.execute(
            sa.select(products.c.id, products.c.sku, products.c.name, products.c.category)
        )
    }
    for sale in connection.execute(
        sa.select(
            sales.c.id,
            sales.c.product_id,
            sales.c.customer_id,
            sales.c.quantity,
            sales.c.total_amount,
            sales.c.sale_date,
        ).order_by(sales.c.id)
    ).mappings():
        order_id = connection.execute(
            orders.insert()
            .values(
                customer_id=sale["customer_id"],
                ordered_at=sale["sale_date"],
                status="completed",
                currency="BRL",
                gross_amount=sale["total_amount"],
                discount_amount=Decimal("0.00"),
                net_amount=sale["total_amount"],
                legacy_sale_id=sale["id"],
            )
            .returning(orders.c.id)
        ).scalar_one()
        quantity = sale["quantity"] or 1
        snapshot = product_snapshots.get(sale["product_id"], (None, None, None))
        connection.execute(
            items.insert().values(
                order_id=order_id,
                product_id=sale["product_id"],
                quantity=quantity,
                unit_price=(sale["total_amount"] / quantity).quantize(Decimal("0.01")),
                discount_amount=Decimal("0.00"),
                net_amount=sale["total_amount"],
                product_sku=snapshot[0],
                product_name=snapshot[1],
                category_name=snapshot[2],
            )
        )


def upgrade() -> None:
    _create_schema()
    _backfill(op.get_bind())


def downgrade() -> None:
    op.drop_table("refunds")
    op.drop_table("order_items")
    op.drop_table("orders")
    with op.batch_alter_table("products") as batch:
        batch.drop_index(op.f("ix_products_category_id"))
        batch.drop_constraint(op.f("fk_products_category_id_categories"), type_="foreignkey")
        batch.drop_column("category_id")
    op.drop_table("categories")
