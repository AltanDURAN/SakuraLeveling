"""Tour solo : progression des joueurs

Revision ID: 5d2c8e1f4a90
Revises: 7b2e9d4a1c58
Create Date: 2026-10-27 09:30:00

Décision de l'auteur (27/10/2026) : la tour solo (`/tour`) a 100 étages, les
mêmes pour tous ; la progression est permanente (une défaite ne coûte que le
ticket), avec une récompense au premier passage de chaque étage et une
récompense quotidienne selon l'étage record.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "5d2c8e1f4a90"
down_revision: Union[str, Sequence[str], None] = "7b2e9d4a1c58"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "player_tower_progress",
        sa.Column("player_id", sa.Integer(), sa.ForeignKey("players.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("best_floor", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("wins", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("daily_claimed_on", sa.Date(), nullable=True),
        sa.Column("best_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("player_tower_progress")
