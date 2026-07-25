"""Placement VISUEL du monstre dans le cadre, PAR MONSTRE ET PAR ÉLÉMENT.

Indépendant :
  • du décor (qui vient du spot partagé de la zone, cf. `farm_zone_loader`) ;
  • du poids de spawn (défini sur la fiche du monstre, cf.
    `mob_element_weight_loader`).

    placements[mob_code][element] = {scale, offset_x, offset_y, shadow}

Chaque monstre peut avoir un placement DIFFÉRENT par élément (ex : gobelin bas
en clairière eau, plus haut en clairière terre). Un couple (monstre, élément)
sans entrée → placement automatique. Cache invalidé par mtime.
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
    """Toutes les entrées de placement par élément d'un monstre :
    {element: {scale, offset_x, offset_y, shadow}}."""
    if not mob_code:
        return {}
    p = _load().get(mob_code)
    return dict(p) if isinstance(p, dict) else {}


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
