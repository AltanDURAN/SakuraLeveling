"""add player_element_essences

Compteur d'essences élémentaires par joueur (miroir de player_element_affinities).
Les essences droppent au kill et sont auto-consommées pour monter l'affinité.

Revision ID: a2c4e6f8b0d1
Revises: f1a2b3c4d5e6
Create Date: 2026-07-13

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a2c4e6f8b0d1'
down_revision: Union[str, Sequence[str], None] = 'f1a2b3c4d5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'player_element_essences',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('player_id', sa.Integer(), nullable=False),
        sa.Column('element', sa.String(length=20), nullable=False),
        sa.Column('count', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['player_id'], ['players.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('player_id', 'element', name='uq_player_element_essence'),
    )
    op.create_index(
        op.f('ix_player_element_essences_player_id'),
        'player_element_essences', ['player_id'], unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f('ix_player_element_essences_player_id'),
        table_name='player_element_essences',
    )
    op.drop_table('player_element_essences')
