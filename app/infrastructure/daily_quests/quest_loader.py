"""Loader des définitions de quêtes quotidiennes (cache module-level).

Pattern identique au weekly. Le pool est plus court avec des objectifs plus
modestes (à faire en 1 jour).
"""

import json
import random
from pathlib import Path

from app.domain.entities.weekly_quest_definition import WeeklyQuestDefinition


CONTENT_PATH = (
    Path(__file__).resolve().parents[2]
    / "infrastructure"
    / "content"
    / "daily_quests.json"
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
    rng = rng or random
    defs = list_definitions()
    if len(defs) <= count:
        return list(defs)
    by_tier: dict[str, list[WeeklyQuestDefinition]] = {}
    for d in defs:
        by_tier.setdefault(d.tier, []).append(d)
    chosen: list[WeeklyQuestDefinition] = []
    for tier in ("easy", "medium", "hard"):
        bucket = by_tier.get(tier, [])
        if bucket and len(chosen) < count:
            chosen.append(rng.choice(bucket))
    remaining = [d for d in defs if d not in chosen]
    while len(chosen) < count and remaining:
        pick = rng.choice(remaining)
        chosen.append(pick)
        remaining.remove(pick)
    return chosen


def clear_cache() -> None:
    global _cache
    _cache = None
