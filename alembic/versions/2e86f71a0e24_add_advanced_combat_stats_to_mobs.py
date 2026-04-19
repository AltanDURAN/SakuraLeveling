"""add advanced combat stats to mobs

Revision ID: 2e86f71a0e24
Revises: e516a14efe8b
Create Date: 2026-04-19 14:45:27.699029

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2e86f71a0e24'
down_revision: Union[str, Sequence[str], None] = 'e516a14efe8b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("mob_definitions", sa.Column("crit_chance", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("mob_definitions", sa.Column("crit_damage", sa.Integer(), nullable=False, server_default="100"))
    op.add_column("mob_definitions", sa.Column("dodge", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("mob_definitions", sa.Column("hp_regeneration", sa.Integer(), nullable=False, server_default="0"))
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
