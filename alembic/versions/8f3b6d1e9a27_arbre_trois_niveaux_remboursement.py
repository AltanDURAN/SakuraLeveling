"""arbre à trois niveaux de classes : remboursement des cases de combat

Revision ID: 8f3b6d1e9a27
Revises: 5c8e2a7f4d19
Create Date: 2026-10-25 16:00:00

Étape 3 de la refonte des rôles (décision de l'auteur, 25/10/2026) : les cases
de combat passent de 1 à 3 points (classes 2, entrées de voie 1), trois
classes de base apparaissent et les spécialisations demandent 27 points dans
leur voie. Les allocations de combat d'avant ne valent plus rien avec ces
coûts : on REMBOURSE chaque point investi hors utilité et on vide ces
allocations. Les cases d'UTILITÉ, dont le coût ne change pas, sont conservées.

Downgrade : rien à faire (les anciennes allocations ne sont pas restaurables ;
les points remboursés restent au joueur).
"""
from typing import Sequence, Union

from alembic import op


revision: str = "8f3b6d1e9a27"
down_revision: Union[str, Sequence[str], None] = "5c8e2a7f4d19"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

#: Cases d'UTILITÉ de l'arbre (coûts inchangés) : seules allocations conservées.
#: Tout le reste est remboursé à 1 point par niveau — toutes les cases de
#: combat d'avant coûtaient 1 point par niveau, y compris celles d'une version
#: PLUS ANCIENNE de l'arbre (codes `atq_*`, `voie_atq`, `aventurier`…) restées
#: en base sans effet ni remboursement possible (constaté sur la beta : pour
#: chaque joueur, points libres + niveaux investis = niveau − 1).
KEPT_UTILITY_CODES = (
    "axe_confort", "axe_confort_1", "axe_confort_2", "axe_drop", "axe_drop_1", "axe_drop_2",
    "axe_or", "axe_or_1", "axe_or_2", "axe_xp", "axe_xp_1", "axe_xp_2",
)


#: Coût par niveau des cases d'utilité (pour le rattrapage ci-dessous).
UTILITY_COSTS = {code: ((1,) if "confort" in code else (1, 2, 3)) for code in KEPT_UTILITY_CODES}


def upgrade() -> None:
    kept = ", ".join(f"'{c}'" for c in KEPT_UTILITY_CODES)
    op.execute(f"""
        UPDATE player_progressions
        SET skill_points = skill_points + (
            SELECT COALESCE(SUM(a.level), 0) FROM player_skill_allocations a
            WHERE a.player_id = player_progressions.player_id AND a.skill_code NOT IN ({kept})
        )
    """)
    op.execute(f"DELETE FROM player_skill_allocations WHERE skill_code NOT IN ({kept})")

    # Rattrapage : la règle est 1 point par niveau. Un joueur de la beta avait
    # perdu des points avec une version plus ancienne de l'arbre (niveau 6,
    # 0 point, rien d'investi). On garantit AU MOINS niveau − 1 − points
    # investis en utilité — sans jamais retirer de points (dons de l'admin).
    bind = op.get_bind()
    spent: dict[int, int] = {}
    for player_id, code, level in bind.exec_driver_sql(
            "SELECT player_id, skill_code, level FROM player_skill_allocations").fetchall():
        costs = UTILITY_COSTS.get(code, (1,))
        spent[player_id] = spent.get(player_id, 0) + sum(costs[:max(0, int(level))])
    for player_id, level, points in bind.exec_driver_sql(
            "SELECT player_id, level, skill_points FROM player_progressions").fetchall():
        owed = max(0, int(level) - 1 - spent.get(player_id, 0))
        if owed > (points or 0):
            bind.exec_driver_sql(
                "UPDATE player_progressions SET skill_points = ? WHERE player_id = ?",
                (owed, player_id))


def downgrade() -> None:
    pass
