"""add dodges_total to player_career_stats

Revision ID: 9f6c9ab82525
Revises: b97dfdd73c8a
Create Date: 2026-05-06 13:44:43.865697

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9f6c9ab82525'
down_revision: Union[str, Sequence[str], None] = 'b97dfdd73c8a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "player_career_stats",
        sa.Column("dodges_total", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("player_career_stats", "dodges_total")
