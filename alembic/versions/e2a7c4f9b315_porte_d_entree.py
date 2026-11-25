"""Porte d'entrée du serveur (fermée avant le lancement de la saison)

Revision ID: e2a7c4f9b315
Revises: c1f7a3e9b246
Create Date: 2026-11-25 12:00:00

`entry_gate` : une ligne au plus. Sans ligne, la porte est ouverte (rien ne
change pour un serveur qui ne s'en sert pas).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "e2a7c4f9b315"
down_revision: Union[str, Sequence[str], None] = "c1f7a3e9b246"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "entry_gate",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("opens_at", sa.DateTime(), nullable=True),
        sa.Column("changed_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("entry_gate")
