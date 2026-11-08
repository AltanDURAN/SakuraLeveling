"""Aventure commencée, par compte Discord

Revision ID: d4b8e2f6a9c3
Revises: b7e3c9a5d2f1
Create Date: 2026-11-08 18:00:00

Parcours d'arrivée : finir ou passer le tutoriel donne le rôle Aventurier,
qui ouvre le reste du serveur. Retenu par compte Discord (comme le
règlement accepté) : ni le reset d'un joueur ni celui de la saison n'y
touchent. Ceux qui ont déjà fini ou passé le tutoriel sont repris.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "d4b8e2f6a9c3"
down_revision: Union[str, Sequence[str], None] = "b7e3c9a5d2f1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "adventurers",
        sa.Column("discord_id", sa.BigInteger(), primary_key=True, autoincrement=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("how", sa.String(length=16), nullable=False),
    )
    op.execute(
        "INSERT INTO adventurers (discord_id, started_at, how) "
        "SELECT p.discord_id, COALESCE(t.updated_at, CURRENT_TIMESTAMP), t.status "
        "FROM player_tutorials t JOIN players p ON p.id = t.player_id "
        "WHERE t.status IN ('passe', 'termine')"
    )


def downgrade() -> None:
    op.drop_table("adventurers")
