"""panoplies par rareté : type de bonus choisi par le joueur

Revision ID: 4e7a1c9d2b58
Revises: 9b3e5f7a2c41
Create Date: 2026-10-24 12:00:00

Les panoplies ne sont plus des familles d'objets : le bonus vient des pièces
portées de même rareté (paliers 2 / 4 / 7, comptage cumulatif). Le joueur
choisit UN type de bonus (`players.panoplie_bonus`).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "4e7a1c9d2b58"
down_revision: Union[str, Sequence[str], None] = "9b3e5f7a2c41"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("players", sa.Column(
        "panoplie_bonus", sa.String(20), nullable=False, server_default="attack"))


def downgrade() -> None:
    with op.batch_alter_table("players") as batch:
        batch.drop_column("panoplie_bonus")
