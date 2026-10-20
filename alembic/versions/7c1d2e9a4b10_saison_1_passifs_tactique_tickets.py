"""saison 1 : tactique de combat, tickets de tour, notifications de cooldown

Revision ID: 7c1d2e9a4b10
Revises: 412a113d5529
Create Date: 2026-10-20 10:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "7c1d2e9a4b10"
down_revision: Union[str, Sequence[str], None] = "412a113d5529"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("players", sa.Column("combat_tactic", sa.String(length=20),
                                       server_default="egoiste", nullable=False))
    op.add_column("player_cooldowns", sa.Column("notified_for", sa.DateTime(), nullable=True))
    op.create_table(
        "player_tower_tickets",
        sa.Column("player_id", sa.Integer(), sa.ForeignKey("players.id"), primary_key=True),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("used", sa.Integer(), server_default="0", nullable=False),
    )


def downgrade() -> None:
    op.drop_table("player_tower_tickets")
    op.drop_column("player_cooldowns", "notified_for")
    op.drop_column("players", "combat_tactic")
