"""add help subscribers (chads)

Revision ID: b97dfdd73c8a
Revises: 7255b0599205
Create Date: 2026-05-03 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b97dfdd73c8a"
down_revision: Union[str, Sequence[str], None] = "7255b0599205"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "help_subscribers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "player_id",
            sa.Integer(),
            sa.ForeignKey("players.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("subscribed_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("help_subscribers")
