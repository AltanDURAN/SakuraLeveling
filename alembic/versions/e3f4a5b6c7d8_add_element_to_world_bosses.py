"""world boss : colonne element sur l'instance active

Ajoute `world_bosses.element` (mono-élément V1, "" = neutre). Persiste sur
l'instance pour permettre à l'admin de changer l'élément du boss actif à chaud.

Revision ID: e3f4a5b6c7d8
Revises: d2e3f4a5b6c7
Create Date: 2026-06-21 00:10:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "e3f4a5b6c7d8"
down_revision: Union[str, Sequence[str], None] = "d2e3f4a5b6c7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "world_bosses",
        sa.Column("element", sa.String(length=20), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("world_bosses", "element")
