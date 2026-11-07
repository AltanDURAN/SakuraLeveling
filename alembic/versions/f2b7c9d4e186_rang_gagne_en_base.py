"""Rang gagné gardé en base, emplacements de compétence retirés

Revision ID: f2b7c9d4e186
Revises: e5c2a8f1d374
Create Date: 2026-11-07 12:00:00

Le rang n'existait que dans le rôle Discord : un joueur qui quittait le serveur
retombait au Rang F en revenant. `skill_slot_1/2` ne servaient plus depuis la
saison 1 (compétences de l'arbre).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "f2b7c9d4e186"
down_revision: Union[str, Sequence[str], None] = "e5c2a8f1d374"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("players") as batch:
        batch.add_column(sa.Column("earned_rank", sa.String(4), nullable=False, server_default="F"))
        batch.drop_column("skill_slot_1")
        batch.drop_column("skill_slot_2")


def downgrade() -> None:
    with op.batch_alter_table("players") as batch:
        batch.add_column(sa.Column("skill_slot_2", sa.String(40), nullable=True))
        batch.add_column(sa.Column("skill_slot_1", sa.String(40), nullable=True))
        batch.drop_column("earned_rank")
