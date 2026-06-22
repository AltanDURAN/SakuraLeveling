"""suppression de players.active_element (source de vérité unique)

L'élément d'attaque d'un joueur dérive désormais de sa compétence OFFENSIVE
équipée (skill_slot_1/2). Le champ `active_element` faisait doublon → supprimé.

Revision ID: a7b8c9d0e1f2
Revises: f4a5b6c7d8e9
Create Date: 2026-06-22 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "a7b8c9d0e1f2"
down_revision: Union[str, Sequence[str], None] = "f4a5b6c7d8e9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("players") as batch_op:
        batch_op.drop_column("active_element")


def downgrade() -> None:
    op.add_column(
        "players",
        sa.Column("active_element", sa.String(length=20), nullable=True),
    )
