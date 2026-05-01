"""add mob family and player mob kills

Revision ID: ecc9ec264b87
Revises: a73787e37f5b
Create Date: 2026-05-01 13:21:05.653550

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'ecc9ec264b87'
down_revision: Union[str, Sequence[str], None] = 'a73787e37f5b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "mob_definitions",
        sa.Column("family", sa.String(length=100), nullable=False, server_default="unknown"),
    )
    op.create_index(
        "ix_mob_definitions_family",
        "mob_definitions",
        ["family"],
    )

    op.create_table(
        "player_mob_kills",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("player_id", sa.Integer(), sa.ForeignKey("players.id", ondelete="CASCADE"), nullable=False),
        sa.Column("mob_code", sa.String(length=100), nullable=False),
        sa.Column("kill_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("player_id", "mob_code", name="uq_player_mob_kills_player_mob"),
    )
    op.create_index(
        "ix_player_mob_kills_player_id",
        "player_mob_kills",
        ["player_id"],
    )
    op.create_index(
        "ix_player_mob_kills_mob_code",
        "player_mob_kills",
        ["mob_code"],
    )


def downgrade() -> None:
    op.drop_index("ix_player_mob_kills_mob_code", table_name="player_mob_kills")
    op.drop_index("ix_player_mob_kills_player_id", table_name="player_mob_kills")
    op.drop_table("player_mob_kills")

    op.drop_index("ix_mob_definitions_family", table_name="mob_definitions")
    op.drop_column("mob_definitions", "family")
