"""add player_career_stats table

Revision ID: 4da37c7728e3
Revises: 7c075a207b31
Create Date: 2026-05-01 22:08:41.411519

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '4da37c7728e3'
down_revision: Union[str, Sequence[str], None] = '7c075a207b31'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "player_career_stats",
        sa.Column(
            "player_id",
            sa.Integer(),
            sa.ForeignKey("players.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("gold_earned_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("damage_dealt_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("damage_tanked_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("hp_healed_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("combats_fought", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("combats_won", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("combats_lost", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("player_career_stats")
