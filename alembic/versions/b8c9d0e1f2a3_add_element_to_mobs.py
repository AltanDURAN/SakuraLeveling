"""ajoute mob_definitions.element (système élémentaire)

Chaque mob simple a un élément propre (mono-élément V1), comme les world boss.
"" = neutre. Administrable via /admin.

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-06-22 00:10:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "b8c9d0e1f2a3"
down_revision: Union[str, Sequence[str], None] = "a7b8c9d0e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "mob_definitions",
        sa.Column("element", sa.String(length=20), nullable=False, server_default=""),
    )


def downgrade() -> None:
    with op.batch_alter_table("mob_definitions") as batch_op:
        batch_op.drop_column("element")
