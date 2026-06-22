"""add mob speed

Revision ID: e516a14efe8b
Revises: 99f9de254432
Create Date: 2026-04-19 00:41:08.351213

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e516a14efe8b'
down_revision: Union[str, Sequence[str], None] = '99f9de254432'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Ajoute la colonne `speed` aux mobs.

    NOTE (correctif chaîne) : l'autogénération d'origine recréait toute la
    table `mob_definitions` (déjà créée par dbe1e648a426 + colonnes ajoutées
    par les migrations intermédiaires), ce qui faisait échouer `upgrade head`
    depuis une base vide (`table already exists`). On ne fait plus qu'ajouter
    la colonne réellement introduite par cette révision.
    """
    op.add_column(
        "mob_definitions",
        sa.Column("speed", sa.Integer(), nullable=False, server_default="5"),
    )


def downgrade() -> None:
    op.drop_column("mob_definitions", "speed")
