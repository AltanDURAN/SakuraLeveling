"""Loader des définitions de quêtes hebdomadaires (cache module-level)."""

import json
import random
from pathlib import Path

from app.domain.entities.weekly_quest_definition import WeeklyQuestDefinition


CONTENT_PATH = (
    Path(__file__).resolve().parents[2]
    / "infrastructure"
    / "content"
    / "weekly_quests.json"
)

_cache: list[WeeklyQuestDefinition] | None = None


def _load() -> list[WeeklyQuestDefinition]:
    with CONTENT_PATH.open("r", encoding="utf-8") as fh:
        raw = json.load(fh)
    return [
        WeeklyQuestDefinition(
            code=item["code"],
            name=item["name"],
            description=item.get("description", ""),
            tier=item.get("tier", "easy"),
            objective_type=item["objective_type"],
            objective_target=item.get("objective_target", ""),
            objective_quantity=int(item["objective_quantity"]),
            reward_gold=int(item.get("reward_gold", 0)),
            reward_xp=int(item.get("reward_xp", 0)),
            reward_items=item.get("reward_items", []) or [],
        )
        for item in raw
    ]


def list_definitions() -> list[WeeklyQuestDefinition]:
    global _cache
    if _cache is None:
        _cache = _load()
    return _cache


def get_definition(code: str) -> WeeklyQuestDefinition | None:
    for d in list_definitions():
        if d.code == code:
            return d
    return None


def list_for_objective_type(objective_type: str) -> list[WeeklyQuestDefinition]:
    return [d for d in list_definitions() if d.objective_type == objective_type]


def pick_random_assignment(
    count: int = 3, rng: random.Random | None = None
) -> list[WeeklyQuestDefinition]:
    """Tire `count` quêtes au hasard sans répétition. Si moins de `count`
    quêtes existent, retourne tout le catalogue. Tirage non pondéré (chaque
    quête a la même chance d'apparaître). Pour varier les difficultés,
    on essaie de prendre un mix easy/medium/hard si possible."""
    rng = rng or random
    defs = list_definitions()
    if len(defs) <= count:
        return list(defs)

    # Mix par tier : 1 easy + 1 medium + 1 hard (si dispo), sinon random fill
    by_tier = {"easy": [], "medium": [], "hard": []}
    for d in defs:
        by_tier.setdefault(d.tier, []).append(d)

    chosen: list[WeeklyQuestDefinition] = []
    for tier in ("easy", "medium", "hard"):
        bucket = by_tier.get(tier, [])
        if bucket and len(chosen) < count:
            chosen.append(rng.choice(bucket))

    # Si on n'a pas assez (ex: tous les défis sont 'easy'), compléter random
    remaining = [d for d in defs if d not in chosen]
    while len(chosen) < count and remaining:
        pick = rng.choice(remaining)
        chosen.append(pick)
        remaining.remove(pick)

    return chosen


def clear_cache() -> None:
    global _cache
    _cache = None
