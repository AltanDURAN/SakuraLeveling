"""Événements saisonniers : cases prises, achats en boutique d'événement,
annonces postées

Revision ID: f5c2e8a1b7d4
Revises: e7c3a9d5b1f8
Create Date: 2026-11-10 12:00:00

Calendrier de l'Avent, cadeau de Noël, boutiques d'événement (monnaie = un
objet, limite par joueur) et annonces du salon des événements (une seule
fois, même après un redémarrage) — cf. `seasonal_events.json`.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "f5c2e8a1b7d4"
down_revision: Union[str, Sequence[str], None] = "e7c3a9d5b1f8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "seasonal_claims",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("player_id", sa.Integer(), sa.ForeignKey("players.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_code", sa.String(40), nullable=False),
        sa.Column("claim_key", sa.String(40), nullable=False),
        sa.Column("claimed_at", sa.DateTime(), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}"),
        sa.UniqueConstraint("player_id", "event_code", "claim_key", name="uq_seasonal_claim"),
    )
    op.create_index("ix_seasonal_claims_player_id", "seasonal_claims", ["player_id"])
    op.create_table(
        "event_shop_purchases",
        sa.Column("player_id", sa.Integer(), sa.ForeignKey("players.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("shop_code", sa.String(40), primary_key=True),
        sa.Column("item_code", sa.String(80), primary_key=True),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "seasonal_announcements",
        sa.Column("key", sa.String(80), primary_key=True),
        sa.Column("posted_at", sa.DateTime(), nullable=False),
        sa.Column("channel_id", sa.BigInteger(), nullable=True),
        sa.Column("message_id", sa.BigInteger(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("seasonal_announcements")
    op.drop_table("event_shop_purchases")
    op.drop_index("ix_seasonal_claims_player_id", table_name="seasonal_claims")
    op.drop_table("seasonal_claims")
