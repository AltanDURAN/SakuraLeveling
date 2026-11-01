"""Surveillance : journal d'événements, photos quotidiennes, alertes

Revision ID: e5c2a8f1d374
Revises: d7a1e5c3b820
Create Date: 2026-11-01 12:00:00
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "e5c2a8f1d374"
down_revision: Union[str, Sequence[str], None] = "d7a1e5c3b820"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "game_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("at", sa.DateTime(), nullable=False),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("player_id", sa.Integer(), nullable=True),
        sa.Column("discord_id", sa.BigInteger(), nullable=True),
        sa.Column("zone", sa.String(32), nullable=True),
        sa.Column("ref", sa.String(80), nullable=True),
        sa.Column("gold", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("xp", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("qty", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("data", sa.Text(), nullable=True),
    )
    op.create_index("ix_game_events_at", "game_events", ["at"])
    op.create_index("ix_game_events_kind_at", "game_events", ["kind", "at"])
    op.create_index("ix_game_events_player_at", "game_events", ["player_id", "at"])

    op.create_table(
        "player_daily_snapshots",
        sa.Column("day", sa.Date(), primary_key=True),
        sa.Column("player_id", sa.Integer(), primary_key=True),
        sa.Column("taken_at", sa.DateTime(), nullable=False),
        sa.Column("level", sa.Integer(), nullable=False),
        sa.Column("xp_total", sa.BigInteger(), nullable=False),
        sa.Column("gold", sa.BigInteger(), nullable=False),
        sa.Column("power", sa.BigInteger(), nullable=False),
        sa.Column("rank", sa.String(8), nullable=False),
        sa.Column("kills", sa.Integer(), nullable=False),
        sa.Column("combats", sa.Integer(), nullable=False),
        sa.Column("wins", sa.Integer(), nullable=False),
        sa.Column("gold_earned", sa.BigInteger(), nullable=False),
        sa.Column("data", sa.Text(), nullable=True),
    )

    op.create_table(
        "monitoring_alerts",
        sa.Column("key", sa.String(160), primary_key=True),
        sa.Column("code", sa.String(40), nullable=False),
        sa.Column("severity", sa.String(12), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("player_id", sa.Integer(), nullable=True),
        sa.Column("first_seen", sa.DateTime(), nullable=False),
        sa.Column("last_seen", sa.DateTime(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("muted_until", sa.DateTime(), nullable=True),
        sa.Column("notified_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("monitoring_alerts")
    op.drop_table("player_daily_snapshots")
    op.drop_index("ix_game_events_player_at", table_name="game_events")
    op.drop_index("ix_game_events_kind_at", table_name="game_events")
    op.drop_index("ix_game_events_at", table_name="game_events")
    op.drop_table("game_events")
