"""Loader des définitions de world boss (cache module-level).

Le JSON est relu dès qu'il change (date de modification) : une image ou une
fiche modifiée depuis le site vaut au prochain boss SANS redémarrer le bot
(11/11/2026). `clear_cache()` force la relecture (tests).
"""

import json
import random
from pathlib import Path

from app.domain.entities.boss_definition import BossDefinition
from app.domain.services import boss_selection_service


CONTENT_PATH = (
    Path(__file__).resolve().parents[2]
    / "infrastructure"
    / "content"
    / "boss_definitions.json"
)


_definitions_cache: list[BossDefinition] | None = None
_cache_mtime: float | None = None


def _load() -> list[BossDefinition]:
    with CONTENT_PATH.open("r", encoding="utf-8") as fh:
        raw = json.load(fh)

    return [
        BossDefinition(
            code=item["code"],
            name=item["name"],
            description=item.get("description", ""),
            image_name=item.get("image_name", ""),
            tier=item.get("tier", "intro"),
            spawn_weight=int(item.get("spawn_weight", 1)),
            max_hp=int(item["max_hp"]),
            attack=int(item["attack"]),
            defense=int(item["defense"]),
            speed=int(item["speed"]),
            crit_chance=int(item.get("crit_chance", 0)),
            crit_damage=int(item.get("crit_damage", 100)),
            dodge=int(item.get("dodge", 0)),
            element=item.get("element", "") or "",
            level=int(item.get("level", 1)),
            modifiers=item.get("modifiers", {}) or {},
            phases=item.get("phases", []) or [],
            ultimate=item.get("ultimate", {}) or {},
            guards=item.get("guards", []) or [],
            loot_table=item.get("loot_table", []) or [],
            lore=item.get("lore", ""),
        )
        for item in raw
    ]


def _mtime() -> float | None:
    try:
        return CONTENT_PATH.stat().st_mtime
    except OSError:
        return None


def list_definitions() -> list[BossDefinition]:
    global _definitions_cache, _cache_mtime
    mtime = _mtime()
    if _definitions_cache is None or mtime != _cache_mtime:
        _definitions_cache = _load()
        _cache_mtime = mtime
    return _definitions_cache


def get_definition(code: str) -> BossDefinition | None:
    for d in list_definitions():
        if d.code == code:
            return d
    return None


def pick_random_definition(
    rng: random.Random | None = None,
    levels: list[int] | None = None,
    previous_code: str = "",
) -> BossDefinition | None:
    """Le boss de la semaine selon les niveaux des joueurs actifs (cf.
    `boss_selection_service`), ou None si le serveur n'est pas prêt.
    Sans `levels` : tirage pondéré par `spawn_weight` (spawn manuel, tests)."""
    rng = rng or random
    defs = list_definitions()
    if not defs:
        return None
    if levels is not None:
        return boss_selection_service.pick(defs, levels, rng, previous_code)
    return rng.choices(defs, weights=[d.spawn_weight for d in defs], k=1)[0]


def clear_cache() -> None:
    """Force le re-chargement du JSON (utile pour les tests)."""
    global _definitions_cache, _cache_mtime
    _definitions_cache = None
    _cache_mtime = None
