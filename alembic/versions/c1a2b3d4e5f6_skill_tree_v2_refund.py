"""skill tree v2 : refund + wipe des allocations (arbre réécrit)

L'arbre de compétences a été entièrement réécrit (modèle V2 : nœuds plats
infinis + spéciaux). Les anciens codes de nœuds (force_brute, vitalite, …)
n'existent plus, donc les allocations existantes pointent dans le vide.

Cette migration :
1. Supprime toutes les allocations (player_skill_allocations).
2. Recrédite chaque joueur : skill_points = max(skill_points actuel, niveau)
   — généreux et jamais réducteur (compense la refonte ; chaque joueur a au
   moins `niveau` points à redépenser dans le nouvel arbre).
3. Purge le cooldown de reset d'arbre pour que les joueurs puissent
   réorganiser librement juste après la refonte.

Note : en V2 les stats de base ne scalent plus avec le niveau — toute la
puissance vient du nouvel arbre + équipement. Le refund permet de
reconstruire son build immédiatement.

Revision ID: c1a2b3d4e5f6
Revises: b5d2a1c93e21
Create Date: 2026-05-25 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op


revision: str = "c1a2b3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "b5d2a1c93e21"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Recrédite les points AVANT de supprimer (jamais réducteur).
    op.execute(
        "UPDATE player_progressions "
        "SET skill_points = MAX(skill_points, level)"
    )
    # 2. Supprime les allocations (codes obsolètes).
    op.execute("DELETE FROM player_skill_allocations")
    # 3. Purge le cooldown de reset d'arbre.
    op.execute(
        "DELETE FROM player_cooldowns WHERE action_key = 'skill_tree_reset'"
    )


def downgrade() -> None:
    # Irréversible (les anciennes allocations sont perdues). No-op.
    pass
