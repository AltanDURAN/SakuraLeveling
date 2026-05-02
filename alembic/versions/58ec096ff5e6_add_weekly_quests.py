"""add weekly quest tracking

Revision ID: 58ec096ff5e6
Revises: 5546a51fa27d
Create Date: 2026-05-02 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "58ec096ff5e6"
down_revision: Union[str, Sequence[str], None] = "5546a51fa27d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "weekly_quest_assignments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "player_id",
            sa.Integer(),
            sa.ForeignKey("players.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        # Date du lundi 00:00 UTC du début de semaine (sert de clé de rotation)
        sa.Column("week_start", sa.DateTime(), nullable=False, index=True),
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
            "player_id", "week_start", "quest_code",
            name="uq_weekly_quest_assignment",
        ),
    )


def downgrade() -> None:
    op.drop_table("weekly_quest_assignments")
