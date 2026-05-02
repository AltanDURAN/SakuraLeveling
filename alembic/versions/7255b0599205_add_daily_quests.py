"""add daily quest tracking

Revision ID: 7255b0599205
Revises: 9154b44b1471
Create Date: 2026-05-03 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "7255b0599205"
down_revision: Union[str, Sequence[str], None] = "9154b44b1471"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "daily_quest_assignments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "player_id",
            sa.Integer(),
            sa.ForeignKey("players.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        # Date du jour 00:00 UTC (sert de clé de rotation quotidienne)
        sa.Column("day_start", sa.DateTime(), nullable=False, index=True),
        sa.Column("quest_code", sa.String(length=100), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "completed", sa.Boolean(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "claimed", sa.Boolean(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "player_id", "day_start", "quest_code",
            name="uq_daily_quest_assignment",
        ),
    )


def downgrade() -> None:
    op.drop_table("daily_quest_assignments")
