"""add daily_streak to player_resources

Revision ID: 7c075a207b31
Revises: db713f373c43
Create Date: 2026-05-01 15:03:06.682143

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '7c075a207b31'
down_revision: Union[str, Sequence[str], None] = 'db713f373c43'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "player_resources",
        sa.Column("daily_streak", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("player_resources", "daily_streak")
