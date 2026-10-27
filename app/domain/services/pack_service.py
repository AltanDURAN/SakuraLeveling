"""Meutes de zone : plusieurs monstres dans un même combat (27/10/2026).

Décidé avec l'auteur : les combats contre plusieurs ennemis arrivent aussi
en zone, de temps en temps (`PACK_CHANCE` des apparitions), en meutes de 2
ou 3 monstres de la zone, de puissance voisine.

  • Chaque monstre d'une meute a ses PV et son ATK × `PACK_SCALE[n]` : le
    joueur de référence seul bat une meute aussi souvent qu'un monstre seul
    de son palier (80 %, le seuil de `test_mob_balance`) — MESURÉ par
    `scripts/calibrate_packs.py` à 7 niveaux, on garde le plus prudent ;
  • l'XP et l'or = la somme des monstres × `PACK_SCALE[n]` × `PACK_BONUS`
    (une meute dure ~1,7 à 2,2 combats et fait plus mal : +25 %) ;
  • chaque monstre compte comme une VICTOIRE (kills, quêtes, titres), mais
    son butin (matériaux, pièce d'équipement, essences) ne tombe qu'avec la
    probabilité `PACK_SCALE[n]` : une meute rapporte autant de butin que les
    monstres « entiers » qu'elle représente, pas trois fois plus ;
  • ni élite (elles sont déjà du contenu de groupe) ni succube (son charme
    est une défaite immédiate seul) dans une meute.
"""

from __future__ import annotations

import random

PACK_CHANCE = 0.10
PACK_SIZE_WEIGHTS: dict[int, int] = {2: 60, 3: 40}
#: Facteur de PV et d'ATK de chaque monstre d'une meute de n (mesuré le 27/10/2026).
PACK_SCALE: dict[int, float] = {1: 1.0, 2: 0.87, 3: 0.73}
PACK_BONUS = 1.25
#: Compagnons d'une puissance comprise entre ces fractions de celle du chef.
POWER_SPREAD = (0.6, 1.6)
EXCLUDED = frozenset({"succube"})


def scale(n: int) -> float:
    return PACK_SCALE.get(n, PACK_SCALE[max(PACK_SCALE)])


def pack_reward(base_rewards: list[int]) -> int:
    """XP ou or d'une meute : la somme de ses monstres × facteur × bonus."""
    n = len(base_rewards)
    if n <= 1:
        return sum(base_rewards)
    return round(sum(base_rewards) * scale(n) * PACK_BONUS)


def loot_roll(n: int, rng: random.Random | None = None) -> bool:
    """Le butin de CE monstre tombe-t-il ? (toujours seul ; × facteur en meute)."""
    return n <= 1 or (rng or random).random() < scale(n)


def pick_pack_size(rng: random.Random | None = None) -> int:
    sizes = sorted(PACK_SIZE_WEIGHTS)
    return (rng or random).choices(sizes, weights=[PACK_SIZE_WEIGHTS[s] for s in sizes], k=1)[0]


def pick_companions(leader, candidates: list, power_of, size: int,
                    rng: random.Random | None = None) -> list:
    """Compagnons du chef pour une meute de `size` (chef compris) : des
    monstres de la zone de puissance voisine, tirés selon leur poids de
    spawn (avec remise : une meute de loups, c'est permis). [] si personne."""
    rng = rng or random
    lead = max(1, power_of(leader))
    pool = [m for m in candidates
            if POWER_SPREAD[0] <= power_of(m) / lead <= POWER_SPREAD[1]]
    if not pool:
        return []
    return rng.choices(pool, weights=[max(1, m.spawn_weight) for m in pool], k=size - 1)
