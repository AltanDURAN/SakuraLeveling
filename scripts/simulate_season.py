"""Simulateur de saison : combien de temps pour aller du niveau 1 au niveau 100 ?

Objectif de la saison 1 : le niveau 100 en ~1 an à ~30 min/jour, sans que les
premiers niveaux tombent tout seuls. Ce script joue un joueur type jour par
jour et mesure :

  • les jours pour atteindre les niveaux clés, et le niveau atteint à J1, J7,
    J30, J90, J180, J365 ;
  • l'or gagné par source (combats, quêtes, raid, /daily), comparé au prix
    d'une tenue complète chez les artisans à chaque palier d'équipement.

Deux mondes sont simulés :
  • « contenu actuel » : les zones et monstres de mobs.json / farm_zones.json,
    ouvertes par rang (épreuve passée au niveau de RANK_LEVELS) ;
  • « zones complètes » : comme si chaque rang avait sa zone, avec des
    monstres au niveau du joueur — la cible de la V1.

    .venv/bin/python -m scripts.simulate_season            # 30 min/jour, 3 min par combat
    .venv/bin/python -m scripts.simulate_season --minutes 60 --cycle 4
"""

from __future__ import annotations

import argparse
import json
import statistics
from dataclasses import dataclass, field
from pathlib import Path

from app.domain.services.artisan_service import ArtisanService
from app.domain.services.item_power_service import ItemPowerService
from app.domain.services.progression_service import (
    LEVEL_CAP,
    XP_PER_KILL_COEF,
    ProgressionService,
)
from app.domain.services.daily_reward_service import daily_gold as daily_reward_gold
from app.domain.services.quest_reward_service import scale_reward
from app.infrastructure.artisans import artisan_loader

CONTENT = Path(__file__).resolve().parents[1] / "app" / "infrastructure" / "content"

#: Niveau auquel un joueur type passe l'épreuve de chaque rang (calibrage des
#: gardiens, cf. scripts/calibrate_rank_trials.py).
RANK_LEVELS = {"F": 1, "E": 12, "D": 25, "C": 38, "B": 50, "A": 63, "S": 75, "SS": 88, "SSS": 100}
#: Zones actuelles → rang requis (cf. mémoire projet « rôles de rang »).
ZONE_RANKS = {"Clairière sinistre": "F", "Cimetière abandonné lumière": "E", "Berceau cataclysmique": "D"}

#: Hypothèses de comportement d'un joueur régulier.
DAILY_QUESTS_DONE = 2      # sur 3 tirées chaque jour
WEEKLY_QUESTS_DONE = 2     # sur 3 tirées chaque lundi
RAID_XP_BASE = 50          # CompleteWorldBossUseCase.XP_PER_TIER (palier 1)
RAID_GOLD_BASE = 50 + 200 * 0.25  # base + part moyenne du pool d'un raid à 4
# /daily : règle réelle du jeu (daily_reward_service), joueur assidu (pas de jour manqué).


def _load(name: str):
    data = json.loads((CONTENT / name).read_text(encoding="utf-8"))
    return data


def _mobs_by_zone() -> dict[str, list[dict]]:
    mobs = _load("mobs.json")
    mobs = mobs if isinstance(mobs, list) else mobs.get("mobs", [])
    zones = _load("farm_zones.json")
    zones = zones["zones"] if isinstance(zones, dict) else zones
    out = {}
    for zone in zones:
        families = set(zone.get("families", []))
        out[zone["name"]] = [m for m in mobs if m.get("family") in families]
    return out


def _quest_means(name: str) -> tuple[float, float]:
    data = _load(name)
    quests = data if isinstance(data, list) else data.get("quests", [])
    return (
        statistics.mean(q.get("reward_xp", 0) for q in quests),
        statistics.mean(q.get("reward_gold", 0) for q in quests),
    )


def rank_for_level(level: int) -> str:
    rank = "F"
    for r, lv in RANK_LEVELS.items():
        if level >= lv:
            rank = r
    return rank


@dataclass
class World:
    """Ce que le joueur peut farmer : (xp, or) moyens par combat à son niveau."""

    name: str
    full_zones: bool
    zones: dict[str, list[dict]] = field(default_factory=dict)

    def per_kill(self, level: int) -> tuple[float, float]:
        if self.full_zones:
            # Monstres à son niveau : la référence de la courbe d'XP.
            return XP_PER_KILL_COEF * level, 3.0 * level
        order = list(RANK_LEVELS)
        best = None
        for zone, rank in ZONE_RANKS.items():
            if order.index(rank) <= order.index(rank_for_level(level)) and self.zones.get(zone):
                mobs = self.zones[zone]
                cand = (
                    statistics.mean(m.get("xp_reward", 0) for m in mobs),
                    statistics.mean(m.get("gold_reward", 0) for m in mobs),
                )
                if best is None or cand[0] > best[0]:
                    best = cand
        return best or (XP_PER_KILL_COEF, 3.0)


@dataclass
class Result:
    days_to: dict[int, int | None]
    level_at: dict[int, int]
    gold: dict[str, float]


def simulate(world: World, minutes_per_day: float, minutes_per_kill: float, days: int = 730) -> Result:
    prog = ProgressionService()
    daily_xp, daily_gold = _quest_means("daily_quests.json")
    weekly_xp, weekly_gold = _quest_means("weekly_quests.json")
    kills_per_day = minutes_per_day / minutes_per_kill

    level, xp, streak = 1, 0, 0
    gold = {"combats": 0.0, "quêtes": 0.0, "raid": 0.0, "daily": 0.0}
    milestones = (5, 10, 25, 50, 75, 100)
    days_to: dict[int, int | None] = {m: None for m in milestones}
    checkpoints = (1, 7, 30, 90, 180, 365, 730)
    level_at: dict[int, int] = {}

    for day in range(1, days + 1):
        gained = 0.0
        xp_kill, gold_kill = world.per_kill(level)
        gained += kills_per_day * xp_kill
        gold["combats"] += kills_per_day * gold_kill

        gained += DAILY_QUESTS_DONE * scale_reward(round(daily_xp), level)
        gold["quêtes"] += DAILY_QUESTS_DONE * scale_reward(round(daily_gold), level)
        if day % 7 == 1:
            gained += WEEKLY_QUESTS_DONE * scale_reward(round(weekly_xp), level)
            gold["quêtes"] += WEEKLY_QUESTS_DONE * scale_reward(round(weekly_gold), level)
            gained += scale_reward(RAID_XP_BASE, level, reference_level=1)
            gold["raid"] += scale_reward(round(RAID_GOLD_BASE), level, reference_level=1)
        streak += 1
        gold["daily"] += daily_reward_gold(level, streak)

        result = prog.apply_level_up(
            current_level=level, current_xp=xp, gained_xp=int(gained),
            current_skill_points=0, current_stat_points=0,
        )
        level, xp = result.level, result.xp
        for m in milestones:
            if days_to[m] is None and level >= m:
                days_to[m] = day
        if day in checkpoints:
            level_at[day] = level
        if level >= LEVEL_CAP and all(d in level_at for d in checkpoints if d <= day):
            pass
    return Result(days_to=days_to, level_at=level_at, gold=gold)


def gear_costs() -> dict[int, int]:
    """Prix (palier Apprenti, sans remise) d'une tenue complète à chaque niveau
    requis : la pièce la plus chère de chaque emplacement disponible."""
    items = _load("items.json")
    items = items if isinstance(items, list) else items.get("items", [])
    artisans = ArtisanService(artisan_loader.load_pricing())
    power = ItemPowerService()
    tier = artisan_loader.get_artisan("forgeron").tiers[0]
    slots = {"tete": 1, "corps": 1, "arme": 2, "accessoire": 3}
    out: dict[int, int] = {}
    levels = sorted({int(i.get("level_requirement", 1)) for i in items if i.get("equipment_slot")})
    for lv in levels:
        total = 0
        for slot, count in slots.items():
            pool = [
                i for i in items
                if i.get("equipment_slot") == slot and int(i.get("level_requirement", 1)) == lv
            ]
            prices = sorted(
                (
                    artisans.gold_cost(
                        power.marginal_power(i.get("stat_bonuses") or {}, lv), tier,
                    )
                    for i in pool
                ),
                reverse=True,
            )
            total += sum(prices[:count])
        out[lv] = total
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Simule une saison de progression.")
    parser.add_argument("--minutes", type=float, default=30, help="minutes de jeu par jour")
    parser.add_argument("--cycle", type=float, default=3, help="minutes par combat (rejoindre → combat → réapparition)")
    args = parser.parse_args()

    zones = _mobs_by_zone()
    print(f"Joueur type : {args.minutes:g} min/jour, {args.cycle:g} min par combat "
          f"→ {args.minutes / args.cycle:.0f} combats/jour, {DAILY_QUESTS_DONE} quêtes/jour, "
          f"{WEEKLY_QUESTS_DONE} hebdo + raid/semaine.\n")
    for world in (World("contenu actuel", False, zones), World("zones complètes", True)):
        r = simulate(world, args.minutes, args.cycle)
        print(f"== {world.name}")
        print("  jours pour atteindre : " + ", ".join(
            f"niv {m} → {d if d is not None else '> 730'}" for m, d in r.days_to.items()))
        print("  niveau atteint      : " + ", ".join(f"J{d} {lv}" for d, lv in r.level_at.items()))
        total = sum(r.gold.values())
        parts = ", ".join(f"{k} {v / total:.0%}" for k, v in r.gold.items())
        print(f"  or cumulé sur 2 ans : {total:,.0f} ({parts})".replace(",", " "))
        print()

    print("== Prix d'une tenue complète (meilleure pièce par emplacement, palier Apprenti)")
    for lv, cost in gear_costs().items():
        print(f"  niveau requis {lv:>3} : {cost:>9,} or".replace(",", " "))


if __name__ == "__main__":
    main()
