"""Loader des MODÈLES de quêtes quotidiennes (cache module-level).

Un modèle devient une quête concrète, adaptée au joueur, au moment du tirage
(`quest_generation_service`) : cible de sa zone, quantité à son niveau,
objectif de son rôle.
"""

import json
from pathlib import Path

from app.domain.services.quest_generation_service import QuestTemplate


CONTENT_PATH = (
    Path(__file__).resolve().parents[2]
    / "infrastructure"
    / "content"
    / "daily_quests.json"
)

_cache: list[QuestTemplate] | None = None
_cache_mtime: float | None = None


def _load() -> list[QuestTemplate]:
    with CONTENT_PATH.open("r", encoding="utf-8") as fh:
        raw = json.load(fh)
    return [
        QuestTemplate(
            code=item["code"],
            name=item["name"],
            description=item.get("description", ""),
            tier=item.get("tier", "easy"),
            objective_type=item["objective_type"],
            quantity=float(item.get("quantity", item.get("objective_quantity", 1))),
            scale=item.get("scale", "count"),
            target=item.get("target", item.get("objective_target", "")) or "",
            roles=tuple(item.get("roles", []) or ()),
            reward_gold=int(item.get("reward_gold", 0)),
            reward_xp=int(item.get("reward_xp", 0)),
            reward_items=item.get("reward_items", []) or [],
        )
        for item in raw
    ]


def _mtime() -> float | None:
    try:
        return CONTENT_PATH.stat().st_mtime
    except OSError:
        return None


def list_definitions() -> list[QuestTemplate]:
    """Relu dès que le fichier change (site admin) : sans redémarrer le bot."""
    global _cache, _cache_mtime
    mtime = _mtime()
    if _cache is None or mtime != _cache_mtime:
        _cache = _load()
        _cache_mtime = mtime
    return _cache


def get_definition(code: str) -> QuestTemplate | None:
    for d in list_definitions():
        if d.code == code:
            return d
    return None


def clear_cache() -> None:
    global _cache, _cache_mtime
    _cache = None
    _cache_mtime = None
