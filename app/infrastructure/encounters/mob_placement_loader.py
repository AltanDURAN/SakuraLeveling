"""Placement du monstre dans le cadre, par monstre.

Indépendant du décor (qui vient du spot de la zone). Un placement =
{scale (hauteur mob / cadre), offset_x (fraction, 0 = centré), shadow,
element_weights {element: poids}}.

`element_weights` définit les éléments que PEUT prendre le monstre : poids > 0 =
éligible (proba relative), 0/absent = non. Vide = le monstre hérite de tous les
éléments de sa zone (avec les poids globaux). Cache invalidé par mtime.
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


def get_mob_placement(mob_code: str | None) -> dict | None:
    if not mob_code:
        return None
    p = _load().get(mob_code)
    return p if isinstance(p, dict) else None


def get_element_weights(mob_code: str | None) -> dict:
    """Poids par élément du monstre (dict possiblement vide)."""
    p = get_mob_placement(mob_code) or {}
    w = p.get("element_weights") or {}
    if not isinstance(w, dict):
        return {}
    out: dict[str, int] = {}
    for k, v in w.items():
        try:
            out[str(k).strip().lower()] = max(0, int(v))
        except (TypeError, ValueError):
            continue
    return out


def reload_cache() -> None:
    global _cache, _cache_mtime
    _cache = None
    _cache_mtime = None
