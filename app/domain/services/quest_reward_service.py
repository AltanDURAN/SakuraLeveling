"""Récompenses de quêtes indexées sur le niveau — SAISON 1.

Avec la courbe d'XP quadratique, une récompense FIXE ne vaut plus rien à haut
niveau : 50 XP font 8 victoires au niveau 1, et moins d'un dixième de victoire
au niveau 80. Une quête doit au contraire peser le MÊME nombre de victoires à
tous les niveaux.

Un monstre rapporte `6,25 × niveau` d'XP et `3 × niveau` d'or : les montants
écrits dans `daily_quests.json` / `weekly_quests.json` sont donc des montants
de NIVEAU 1, multipliés par le niveau du joueur quand il réclame.
"""

from __future__ import annotations

from app.domain.services.progression_service import LEVEL_CAP


def scale_reward(base_amount: int, player_level: int) -> int:
    """Montant de niveau 1 → montant au niveau du joueur."""
    level = max(1, min(int(player_level or 1), LEVEL_CAP))
    return max(0, int(base_amount)) * level
