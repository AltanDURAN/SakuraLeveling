"""add player_titles

Revision ID: 5546a51fa27d
Revises: 8f5906a66f85
Create Date: 2026-05-02 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "5546a51fa27d"
down_revision: Union[str, Sequence[str], None] = "8f5906a66f85"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "player_titles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "player_id",
            sa.Integer(),
            sa.ForeignKey("players.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("title_code", sa.String(length=100), nullable=False),
        sa.Column("unlocked_at", sa.DateTime(), nullable=False),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("0")
        ),
        sa.UniqueConstraint("player_id", "title_code", name="uq_player_title_code"),
    )


def downgrade() -> None:
    op.drop_table("player_titles")
