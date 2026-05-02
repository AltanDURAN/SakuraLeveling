"""add trades and trade_items

Revision ID: a1df1cf955a9
Revises: 559b131677cb
Create Date: 2026-05-02 08:27:02.844291

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a1df1cf955a9'
down_revision: Union[str, Sequence[str], None] = '559b131677cb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "trades",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "initiator_player_id",
            sa.Integer(),
            sa.ForeignKey("players.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "target_player_id",
            sa.Integer(),
            sa.ForeignKey("players.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("initiator_gold_offered", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("target_gold_offered", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_trades_status", "trades", ["status"])

    op.create_table(
        "trade_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "trade_id",
            sa.Integer(),
            sa.ForeignKey("trades.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        # 'initiator' ou 'target' : qui propose cet item
        sa.Column("offered_by", sa.String(length=20), nullable=False),
        sa.Column(
            "item_definition_id",
            sa.Integer(),
            sa.ForeignKey("item_definitions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("trade_items")
    op.drop_index("ix_trades_status", table_name="trades")
    op.drop_table("trades")
