"""saison 1 : talents élémentaires (nouveau tirage pour tout le monde)

Revision ID: 8d2f4a6c1e33
Revises: 7c1d2e9a4b10
Create Date: 2026-10-21 10:00:00

Ajoute talent / plafond / découvert sur les affinités, puis REFAIT le tirage de
tous les joueurs existants : affinités et essences remises à 0 (décision de
l'auteur — le bot est fermé, la saison 1 repart de zéro de toute façon).
"""
import random
from datetime import datetime, UTC
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "8d2f4a6c1e33"
down_revision: Union[str, Sequence[str], None] = "7c1d2e9a4b10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("player_element_affinities", sa.Column("talent", sa.Integer(), nullable=True))
    op.add_column("player_element_affinities", sa.Column(
        "affinity_cap", sa.Integer(), server_default="100", nullable=False))
    op.add_column("player_element_affinities", sa.Column(
        "revealed", sa.Boolean(), server_default="0", nullable=False))

    from app.domain.services.element_talent_service import roll_talents

    bind = op.get_bind()
    now = datetime.now(UTC).replace(tzinfo=None)
    player_ids = [row[0] for row in bind.execute(sa.text("SELECT id FROM players"))]
    for pid in player_ids:
        bind.execute(sa.text("DELETE FROM player_element_affinities WHERE player_id = :p"), {"p": pid})
        for element, t in roll_talents(random.SystemRandom()).items():
            bind.execute(sa.text(
                "INSERT INTO player_element_affinities "
                "(player_id, element, value, talent, affinity_cap, revealed, created_at, updated_at) "
                "VALUES (:p, :e, 0, :t, :c, 0, :n, :n)"
            ), {"p": pid, "e": element, "t": t.talent, "c": t.cap, "n": now})
    bind.execute(sa.text("UPDATE player_element_essences SET count = 0"))


def downgrade() -> None:
    op.drop_column("player_element_affinities", "revealed")
    op.drop_column("player_element_affinities", "affinity_cap")
    op.drop_column("player_element_affinities", "talent")
