"""add shop_items table

Revision ID: db713f373c43
Revises: ecc9ec264b87
Create Date: 2026-05-01 14:25:03.934860

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'db713f373c43'
down_revision: Union[str, Sequence[str], None] = 'ecc9ec264b87'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "shop_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "item_definition_id",
            sa.Integer(),
            sa.ForeignKey("item_definitions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("buy_price", sa.Integer(), nullable=False),
        sa.Column("max_sell_price", sa.Integer(), nullable=False),
        sa.Column("min_sell_price", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("stock_threshold", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("current_stock", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("item_definition_id", name="uq_shop_items_item_definition_id"),
    )
    op.create_index(
        "ix_shop_items_item_definition_id",
        "shop_items",
        ["item_definition_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_shop_items_item_definition_id", table_name="shop_items")
    op.drop_table("shop_items")
