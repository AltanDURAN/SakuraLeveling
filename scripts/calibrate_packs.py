"""Calibre les MEUTES de zone : le facteur (PV et ATK) appliqué à chaque
monstre d'une meute de 2 ou 3, pour que le joueur de RÉFÉRENCE seul la batte
aussi souvent qu'un monstre seul de son palier (`TARGET_WIN`, le seuil de
`test_mob_balance`). Mesuré sur des monstres standard à plusieurs niveaux ;
on garde le plus prudent (le plus petit facteur).

Usage : .venv/bin/python -m scripts.calibrate_packs
"""

from __future__ import annotations

import random

from app.domain.services.party_combat_service import EnemySetup, PartyCombatService
from app.domain.services.reference_player import reference_stats

TARGET_WIN = 0.80
LEVELS = (5, 15, 30, 45, 60, 75, 90)
SIMULATIONS = 60


def win_rate(level: int, n: int, k: float) -> float:
    from scripts.restat_mobs import as_mob, restat

    base = restat(level, "standard")
    mob = as_mob("m", {**base, "max_hp": round(base["max_hp"] * k), "attack": round(base["attack"] * k)})
    stats = reference_stats(level)
    wins = 0
    for seed in range(SIMULATIONS):
        random.seed(seed)
        member = {"player_id": 1, "user_id": 1, "name": "ref", "avatar_url": "", "stats": stats,
                  "current_hp": stats.max_hp, "max_hp": stats.max_hp,
                  "current_mana": stats.mana_max, "mana_max": stats.mana_max}
        wins += PartyCombatService().fight_party_vs_mobs(
            [member], [EnemySetup(mob=mob) for _ in range(n)]).victory
    return wins / SIMULATIONS


def factor(level: int, n: int) -> float:
    lo, hi = 0.2, 1.2
    for _ in range(10):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if win_rate(level, n, mid) >= TARGET_WIN else (lo, mid)
    return round(lo, 2)


def main() -> None:
    for n in (1, 2, 3):
        values = {lvl: factor(lvl, n) for lvl in LEVELS}
        print(f"meute de {n} : " + " ".join(f"niv {l}: ×{v}" for l, v in values.items())
              + f"  → retenu ×{min(values.values())}")


if __name__ == "__main__":
    main()
