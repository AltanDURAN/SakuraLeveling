"""Placement du monstre dans le cadre, PAR MONSTRE ET PAR ÉLÉMENT.

Indépendant du décor (qui vient du spot partagé de la zone). Chaque monstre peut
avoir un placement DIFFÉRENT par élément :
    placements[mob_code][element] = {weight, scale, offset_x, offset_y, shadow}
`weight` > 0 = le monstre peut spawner sous cet élément (proba relative) ;
0/absent = non. Un monstre sans aucune entrée hérite de tous les éléments de sa
zone (poids globaux) avec un placement automatique. Cache invalidé par mtime.
"""

from __future__ import annotations

import json
from pathlib import Path

CONTENT_PATH = Path(__file__).resolve().parents[1] / "content" / "mob_placements.json"

_cache: dict | None = None
_cache_mtime: float | None = None


def _load() -> dict:
    global _cache, _cache_mtime
    try:
        mtime = CONTENT_PATH.stat().st_mtime
    except OSError:
        mtime = None
    if _cache is None or mtime != _cache_mtime:
        data: dict = {}
        if CONTENT_PATH.exists():
            try:
                with CONTENT_PATH.open("r", encoding="utf-8") as fh:
                    raw = json.load(fh)
                data = raw.get("placements", {}) if isinstance(raw, dict) else {}
            except (ValueError, OSError):
                data = {}
        _cache = data if isinstance(data, dict) else {}
        _cache_mtime = mtime
    return _cache


def all_placements() -> dict:
    return dict(_load())


def get_mob_elements(mob_code: str | None) -> dict:
    """Toutes les entrées par élément d'un monstre : {element: {weight, scale,
    offset_x, offset_y, shadow}}."""
    if not mob_code:
        return {}
    p = _load().get(mob_code)
    return dict(p) if isinstance(p, dict) else {}


def get_element_weights(mob_code: str | None) -> dict:
    """Poids par élément (>0 = éligible). Vide → hérite de la zone."""
    out: dict[str, int] = {}
    for elem, entry in get_mob_elements(mob_code).items():
        if not isinstance(entry, dict):
            continue
        try:
            w = max(0, int(entry.get("weight", 0)))
        except (TypeError, ValueError):
            w = 0
        if w > 0:
            out[str(elem).strip().lower()] = w
    return out


def get_placement(mob_code: str | None, element: str | None) -> dict | None:
    """Placement {scale, offset_x, offset_y, shadow} du couple (monstre,
    élément), ou None (→ placement automatique)."""
    if not mob_code or not element:
        return None
    entry = get_mob_elements(mob_code).get(str(element).strip().lower())
    if not isinstance(entry, dict):
        return None
    return {
        "scale": entry.get("scale", 0.6),
        "offset_x": entry.get("offset_x", 0.0),
        "offset_y": entry.get("offset_y", 0.0),
        "shadow": entry.get("shadow", True),
    }


def reload_cache() -> None:
    global _cache, _cache_mtime
    _cache = None
    _cache_mtime = None
