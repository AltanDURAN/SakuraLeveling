"""compétences élémentaires : 2 emplacements équipés par joueur

Ajoute `players.skill_slot_1` et `players.skill_slot_2` (codes de compétence
'<element>_<role>', NULL = vide). Équipés par défaut au prochain accès
(offensive + support de l'élément préféré) via le backfill paresseux.

Revision ID: f4a5b6c7d8e9
Revises: e3f4a5b6c7d8
Create Date: 2026-06-21 00:20:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "f4a5b6c7d8e9"
down_revision: Union[str, Sequence[str], None] = "e3f4a5b6c7d8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("players", sa.Column("skill_slot_1", sa.String(length=40), nullable=True))
    op.add_column("players", sa.Column("skill_slot_2", sa.String(length=40), nullable=True))


def downgrade() -> None:
    op.drop_column("players", "skill_slot_2")
    op.drop_column("players", "skill_slot_1")
