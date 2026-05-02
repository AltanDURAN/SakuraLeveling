"""add player_duel_ranks

Revision ID: 6dd9ebb70614
Revises: a1df1cf955a9
Create Date: 2026-05-02 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "6dd9ebb70614"
down_revision: Union[str, Sequence[str], None] = "a1df1cf955a9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "player_duel_ranks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "player_id",
            sa.Integer(),
            sa.ForeignKey("players.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("rank_position", sa.Integer(), nullable=False),
        sa.Column("wins", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("losses", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_player_duel_ranks_rank_position",
        "player_duel_ranks",
        ["rank_position"],
    )


def downgrade() -> None:
    op.drop_index("ix_player_duel_ranks_rank_position", table_name="player_duel_ranks")
    op.drop_table("player_duel_ranks")
