"""Loader des définitions de world boss (cache module-level).

Pattern identique à `skill_tree_loader` : on parse le JSON une seule fois
au premier appel et on garde le résultat en mémoire. Pour rafraîchir
(édition à chaud du JSON), appeler `clear_cache()`.
"""

import json
import random
from pathlib import Path

from app.domain.entities.boss_definition import BossDefinition


CONTENT_PATH = (
    Path(__file__).resolve().parents[2]
    / "infrastructure"
    / "content"
    / "boss_definitions.json"
)


_definitions_cache: list[BossDefinition] | None = None


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
            modifiers=item.get("modifiers", {}) or {},
            lore=item.get("lore", ""),
        )
        for item in raw
    ]


def list_definitions() -> list[BossDefinition]:
    global _definitions_cache
    if _definitions_cache is None:
        _definitions_cache = _load()
    return _definitions_cache


def get_definition(code: str) -> BossDefinition | None:
    for d in list_definitions():
        if d.code == code:
            return d
    return None


def pick_random_definition(rng: random.Random | None = None) -> BossDefinition | None:
    """Sélection pondérée par `spawn_weight`. Retourne None si aucun boss
    défini. Utilisé par l'auto-spawn loop."""
    rng = rng or random
    defs = list_definitions()
    if not defs:
        return None
    weights = [d.spawn_weight for d in defs]
    return rng.choices(defs, weights=weights, k=1)[0]


def clear_cache() -> None:
    """Force le re-chargement du JSON (utile pour les tests)."""
    global _definitions_cache
    _definitions_cache = None
