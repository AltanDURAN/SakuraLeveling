"""Cartes à collectionner : l'état de chaque joueur

Revision ID: e7c3a9d5b1f8
Revises: d4b8e2f6a9c3
Create Date: 2026-11-09 18:00:00

Les cartes sont des objets d'inventaire (catégorie `carte`, créés par
`seed_content` depuis `cards.json`) ; cette table garde ce que l'inventaire
ne dit pas : pétales, compteur de la pitié, booster offert, et quand l'album
a grandi pour la dernière fois (départage du record).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "e7c3a9d5b1f8"
down_revision: Union[str, Sequence[str], None] = "d4b8e2f6a9c3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "player_card_states",
        sa.Column("player_id", sa.Integer(), sa.ForeignKey("players.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("petals", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("boosters_opened", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("since_top", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("free_booster_used", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("album_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("album_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("player_card_states")
