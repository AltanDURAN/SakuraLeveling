"""add world_bosses and participations

Revision ID: 8f5906a66f85
Revises: 6dd9ebb70614
Create Date: 2026-05-02 13:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "8f5906a66f85"
down_revision: Union[str, Sequence[str], None] = "6dd9ebb70614"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "world_bosses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("image_name", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("max_hp", sa.Integer(), nullable=False),
        sa.Column("current_hp", sa.Integer(), nullable=False),
        sa.Column("attack", sa.Integer(), nullable=False),
        sa.Column("defense", sa.Integer(), nullable=False),
        sa.Column("speed", sa.Integer(), nullable=False),
        sa.Column("crit_chance", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("crit_damage", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("dodge", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("hp_regeneration", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "status", sa.String(length=20), nullable=False, server_default="active"
        ),
        sa.Column("spawned_at", sa.DateTime(), nullable=False),
        sa.Column("defeated_at", sa.DateTime(), nullable=True),
        sa.Column("channel_message_id", sa.BigInteger(), nullable=True),
    )
    op.create_index("ix_world_bosses_status", "world_bosses", ["status"])

    op.create_table(
        "world_boss_participations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "boss_id",
            sa.Integer(),
            sa.ForeignKey("world_bosses.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "player_id",
            sa.Integer(),
            sa.ForeignKey("players.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "joined", sa.Boolean(), nullable=False, server_default=sa.text("1")
        ),
        sa.Column("damage_dealt", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("damage_tanked", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("hp_healed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("fights_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("boss_id", "player_id", name="uq_world_boss_participation"),
    )


def downgrade() -> None:
    op.drop_table("world_boss_participations")
    op.drop_index("ix_world_bosses_status", table_name="world_bosses")
    op.drop_table("world_bosses")
