"""Tutoriel /tuto : progression et récompense par joueur

Revision ID: c4e8a2d6f913
Revises: b3f1d8e2a457
Create Date: 2026-10-31 12:00:00
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "c4e8a2d6f913"
down_revision: Union[str, Sequence[str], None] = "b3f1d8e2a457"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "player_tutorials",
        sa.Column("player_id", sa.Integer(), sa.ForeignKey("players.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="en_cours"),
        sa.Column("step", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rewarded_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("player_tutorials")
