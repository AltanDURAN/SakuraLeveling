"""add player_mana_states

Table du mana COURANT, miroir de player_health_states. Le mana max et la
régénération sont des stats calculées (base + arbre) ; seul le mana courant
est persisté ici.

Revision ID: f1a2b3c4d5e6
Revises: b8c9d0e1f2a3
Create Date: 2026-07-12

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f1a2b3c4d5e6'
down_revision: Union[str, Sequence[str], None] = 'b8c9d0e1f2a3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'player_mana_states',
        sa.Column('player_id', sa.Integer(), nullable=False),
        sa.Column('current_mana', sa.Integer(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['player_id'], ['players.id']),
        sa.PrimaryKeyConstraint('player_id'),
    )


def downgrade() -> None:
    op.drop_table('player_mana_states')
