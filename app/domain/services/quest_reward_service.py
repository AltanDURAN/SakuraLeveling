"""Récompenses de quêtes indexées sur le niveau — SAISON 1.

Avec la courbe d'XP quadratique, une récompense FIXE ne vaut plus rien à haut
niveau : 50 XP font 8 victoires au niveau 1, et moins d'un dixième de victoire
au niveau 80. Une quête doit au contraire peser le MÊME poids à tous les
niveaux : elle suit donc le niveau, comme l'XP et l'or des monstres
(`6,25 × niveau` d'XP, `3 × niveau` d'or par victoire).

Le montant écrit dans `daily_quests.json` / `weekly_quests.json` est la
récompense au NIVEAU DE RÉFÉRENCE (20) ; au niveau 40 elle double, au niveau 10
elle est divisée par deux.

⚠️ Pourquoi 20 et pas 1 : simulé (`scripts/simulate_season.py`), un joueur à
30 min/jour atteint le niveau 100 en ~350 jours avec les seuls combats — pile
l'objectif d'un an. Avec des montants « de niveau 1 » multipliés par le niveau,
les quêtes valaient 2,5 fois les combats et la saison tombait à 63 jours. Les
quêtes doivent rester un bonus, pas la source principale de progression.
"""

from __future__ import annotations

from app.domain.services.progression_service import LEVEL_CAP

#: Niveau auquel le joueur reçoit exactement le montant écrit dans le JSON.
QUEST_REFERENCE_LEVEL = 20


def scale_reward(
    base_amount: int, player_level: int, reference_level: int = QUEST_REFERENCE_LEVEL,
) -> int:
    """Montant écrit (au niveau de référence) → montant au niveau du joueur."""
    level = max(1, min(int(player_level or 1), LEVEL_CAP))
    return max(0, round(max(0, int(base_amount)) * level / max(1, reference_level)))
