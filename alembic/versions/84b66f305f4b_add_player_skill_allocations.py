"""add player_skill_allocations

Revision ID: 84b66f305f4b
Revises: 4da37c7728e3
Create Date: 2026-05-02 04:04:58.755297

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '84b66f305f4b'
down_revision: Union[str, Sequence[str], None] = '4da37c7728e3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "player_skill_allocations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "player_id",
            sa.Integer(),
            sa.ForeignKey("players.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("skill_code", sa.String(length=100), nullable=False),
        sa.Column("level", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "player_id",
            "skill_code",
            name="uq_player_skill_allocations_player_skill",
        ),
    )
    op.create_index(
        "ix_player_skill_allocations_player_id",
        "player_skill_allocations",
        ["player_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_player_skill_allocations_player_id",
        table_name="player_skill_allocations",
    )
    op.drop_table("player_skill_allocations")
