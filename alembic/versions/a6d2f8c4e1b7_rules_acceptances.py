"""Règlement accepté, par compte Discord

Revision ID: a6d2f8c4e1b7
Revises: f2b7c9d4e186
Create Date: 2026-11-07 15:00:00

On accepte le règlement avant d'avoir accès au bot. Clé = identifiant
Discord (on accepte avant d'avoir un personnage) ; ni le reset d'un joueur ni
celui de la saison n'y touchent.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "a6d2f8c4e1b7"
down_revision: Union[str, Sequence[str], None] = "f2b7c9d4e186"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "rules_acceptances",
        sa.Column("discord_id", sa.BigInteger(), primary_key=True, autoincrement=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("accepted_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("rules_acceptances")
