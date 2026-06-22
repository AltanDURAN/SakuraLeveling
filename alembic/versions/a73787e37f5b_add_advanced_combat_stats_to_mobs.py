"""add advanced combat stats to mobs

Revision ID: a73787e37f5b
Revises: 2e86f71a0e24
Create Date: 2026-04-19 16:58:09.226482

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a73787e37f5b'
down_revision: Union[str, Sequence[str], None] = '2e86f71a0e24'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # NO-OP (correctif chaîne) : les 4 colonnes crit_chance/crit_damage/dodge/
    # hp_regeneration sont DÉJÀ ajoutées par la révision parente 2e86f71a0e24.
    # Cette migration (même nom, autogénérée en double) les ré-ajoutait →
    # `duplicate column name` lors d'un `upgrade head` depuis une base vide.
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
