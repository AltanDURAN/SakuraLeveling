"""Amélioration d'équipement — SAISON 1.

Une pièce va de **+0 à +10**. Chaque niveau ajoute **+10 % de ses propres
bonus** : une pièce à +10 vaut le double d'une pièce neuve, pas davantage.

On gagne un niveau de deux façons :
  • en FUSIONNANT une copie identique de la pièce chez l'artisan qui la
    fabrique, contre de l'or (le prix monte avec le niveau visé) ;
  • grâce à la forge sacrée (événement), qui offre un niveau gratuit.

⚠️ Avant la saison 1, chaque niveau rajoutait 100 % des bonus (+10 = ×11). Avec
des bonus exprimés en POURCENTAGE du socle, ça suffisait à faire sauter le
plafond de cumul à lui seul : une pièce légendaire à +10 valait plus que tout
le reste de l'équipement réuni.

Les niveaux sont stockés PAR DÉFINITION d'objet (`player_item_levels`), car
les objets sont rangés par pile dans l'inventaire : deux copies d'une même
épée partagent son niveau.
"""

from __future__ import annotations

import math

#: Niveau maximal d'une pièce (fusion et forge sacrée confondues).
MAX_ITEM_LEVEL = 10

#: Part des bonus de la pièce ajoutée par niveau.
BONUS_PER_LEVEL = 0.10


def clamp_level(level: int | None) -> int:
    return max(0, min(MAX_ITEM_LEVEL, int(level or 0)))


def level_multiplier(level: int | None) -> float:
    """Multiplicateur appliqué aux bonus d'une pièce : ×1,0 à +0, ×2,0 à +10."""
    return 1.0 + BONUS_PER_LEVEL * clamp_level(level)


def scaled_bonuses(bonuses: dict | None, level: int | None) -> dict:
    """Bonus d'une pièce à un niveau donné, arrondis pour l'affichage.

    Les clés non numériques (effets de consommable…) sont laissées telles
    quelles : on ne multiplie que des nombres.
    """
    mult = level_multiplier(level)
    out: dict = {}
    for key, value in (bonuses or {}).items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            out[key] = value
            continue
        scaled = value * mult
        out[key] = int(scaled) if float(scaled).is_integer() else round(scaled, 1)
    return out


def copies_required(equipped_count: int) -> int:
    """Copies à posséder pour fusionner.

    On en garde une par emplacement où la pièce est portée (on peut porter
    deux fois la même arme) et on en sacrifie une : jamais moins de deux.
    """
    return max(2, int(equipped_count) + 1)


def fusion_gold_cost(craft_gold_cost: int, current_level: int, pct_per_level: int) -> int:
    """Or demandé pour passer de `current_level` à `current_level + 1`.

    Proportionnel au prix de fabrication de la pièce : passer à +1 coûte
    `pct_per_level` % de ce prix, passer à +10 en coûte dix fois plus. Un
    objet cher à fabriquer est cher à améliorer — c'est un puits d'or qui
    grandit avec le joueur.
    """
    target = clamp_level(current_level) + 1
    return max(1, math.ceil(max(0, craft_gold_cost) * pct_per_level / 100 * target))
