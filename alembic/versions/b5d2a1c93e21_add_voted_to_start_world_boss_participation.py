"""add voted_to_start to world_boss_participations

Revision ID: b5d2a1c93e21
Revises: a3e9c7b218fa
Create Date: 2026-05-14 11:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b5d2a1c93e21"
down_revision: Union[str, Sequence[str], None] = "a3e9c7b218fa"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "world_boss_participations",
        sa.Column(
            "voted_to_start", sa.Boolean(),
            nullable=False, server_default=sa.text("0"),
        ),
    )


def downgrade() -> None:
    op.drop_column("world_boss_participations", "voted_to_start")
