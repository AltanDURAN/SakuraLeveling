"""système élémentaire : affinités joueur + élément actif

Ajoute :
1. la table `player_element_affinities` (player_id, element, value 0..100),
   une ligne par (joueur, élément) — affinité tirée aléatoirement à la
   création du profil, améliorable plus tard via un item d'affinité ;
2. la colonne `active_element` sur `players` (élément actif choisi par le
   joueur, NULL = pas encore choisi → résolu sur l'affinité la plus haute).

Backfill : les affinités des joueurs déjà existants sont initialisées par le
bot au prochain accès (init idempotente côté repository) — pas de backfill SQL
ici pour garder l'aléatoire côté application.

Revision ID: d2e3f4a5b6c7
Revises: c1a2b3d4e5f6
Create Date: 2026-06-21 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "d2e3f4a5b6c7"
down_revision: Union[str, Sequence[str], None] = "c1a2b3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "player_element_affinities",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "player_id", sa.Integer(),
            sa.ForeignKey("players.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("element", sa.String(length=20), nullable=False),
        sa.Column("value", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("player_id", "element", name="uq_player_element"),
    )
    op.create_index(
        "ix_player_element_affinities_player_id",
        "player_element_affinities", ["player_id"],
    )
    op.add_column(
        "players",
        sa.Column("active_element", sa.String(length=20), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("players", "active_element")
    op.drop_index(
        "ix_player_element_affinities_player_id",
        table_name="player_element_affinities",
    )
    op.drop_table("player_element_affinities")
