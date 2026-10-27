"""Étages de la tour solo (`tower_floors.json`, généré par scripts/build_tower.py).

Cache module-level, comme les autres loaders de contenu : une modification
du fichier ⇒ redémarrage du bot.
"""

from __future__ import annotations

import json
from pathlib import Path

_CONTENT = Path(__file__).resolve().parents[1] / "content" / "tower_floors.json"
_cache: dict[int, dict] | None = None


def _floors() -> dict[int, dict]:
    global _cache
    if _cache is None:
        data = json.loads(_CONTENT.read_text(encoding="utf-8")) if _CONTENT.exists() else {}
        _cache = {int(f["floor"]): f for f in data.get("floors", [])}
    return _cache


def get_floor(floor: int) -> dict | None:
    return _floors().get(int(floor))


def floor_count() -> int:
    return len(_floors())


def floor_material(floor: int) -> str | None:
    """Matériau de fusion de l'étage : celui de la famille du boss (étages de
    boss), sinon de la famille la plus représentée parmi ses monstres."""
    from app.infrastructure.loot.family_drop_loader import get_family_drops

    data = get_floor(floor)
    if not data:
        return None
    enemies = data.get("enemies", [])
    boss = next((e for e in enemies if e.get("boss")), None)
    families = [boss["family"]] if boss else [e.get("family", "") for e in enemies]
    family = max(families, key=families.count) if families else ""
    cfg = get_family_drops().get(family) or {}
    return cfg.get("item_code") or None


def clear_cache() -> None:
    global _cache
    _cache = None
