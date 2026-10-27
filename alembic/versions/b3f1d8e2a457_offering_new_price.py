"""Offrande commune : nouveau prix de départ (1 500 or)

Revision ID: b3f1d8e2a457
Revises: 9e4a7c2b6d13
Create Date: 2026-10-27 12:00:00

Formule de l'auteur (27/10/2026) : départ 1 500 or, puis (prix + 75 × jauges
remplies) × 1,04 à chaque remplissage, −2 % par jour sans. Une jauge jamais
remplie repart au nouveau prix de départ.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "b3f1d8e2a457"
down_revision: Union[str, Sequence[str], None] = "9e4a7c2b6d13"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("UPDATE offering_state SET target = 1500 WHERE fills = 0")


def downgrade() -> None:
    op.execute("UPDATE offering_state SET target = 25000 WHERE fills = 0")
