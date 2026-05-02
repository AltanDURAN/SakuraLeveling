"""add marketplace listings

Revision ID: 9154b44b1471
Revises: 58ec096ff5e6
Create Date: 2026-05-02 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "9154b44b1471"
down_revision: Union[str, Sequence[str], None] = "58ec096ff5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "marketplace_listings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "seller_player_id",
            sa.Integer(),
            sa.ForeignKey("players.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "item_definition_id",
            sa.Integer(),
            sa.ForeignKey("item_definitions.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("price_per_unit", sa.Integer(), nullable=False),
        # status : "active" | "sold" | "expired" | "cancelled"
        sa.Column(
            "status", sa.String(length=20), nullable=False, server_default="active"
        ),
        sa.Column("listed_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("closed_at", sa.DateTime(), nullable=True),
        # Buyer rempli au moment de la vente complète (None si partiel ou
        # encore actif). Pour tracer la transaction.
        sa.Column(
            "last_buyer_player_id",
            sa.Integer(),
            sa.ForeignKey("players.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_marketplace_listings_status", "marketplace_listings", ["status"]
    )


def downgrade() -> None:
    op.drop_index(
        "ix_marketplace_listings_status", table_name="marketplace_listings"
    )
    op.drop_table("marketplace_listings")
