"""FORMATIONS des combats contre plusieurs monstres (meutes, tour), par zone.

    formations[clé][n] = [{x, y, scale}, …]   (n = 2, 3 ou 4 monstres)

`clé` = l'identifiant du salon de la zone (en texte). Un emplacement : `x` = décalage
horizontal depuis le centre (fraction de la largeur), `y` = décalage vertical
(fraction de la hauteur, < 0 = plus loin, donc dessiné DERRIÈRE), `scale` =
multiplicateur de la taille propre du monstre (son placement par élément,
sinon la taille automatique). Édité depuis l'admin (Scènes › Formations) ;
une clé sans formation reprend `DEFAULT_FORMATIONS`. Cache invalidé par mtime.
"""

from __future__ import annotations

import json
from pathlib import Path

CONTENT_PATH = Path(__file__).resolve().parents[1] / "content" / "mob_formations.json"
SIZES = (2, 3, 4)

#: Formations par défaut : en arc, les côtés un peu en avant et plus grands.
DEFAULT_FORMATIONS: dict[int, list[dict]] = {
    2: [{"x": -0.22, "y": 0.0, "scale": 0.85}, {"x": 0.22, "y": 0.0, "scale": 0.85}],
    3: [{"x": -0.30, "y": 0.02, "scale": 0.75}, {"x": 0.0, "y": -0.05, "scale": 0.75},
        {"x": 0.30, "y": 0.02, "scale": 0.75}],
    4: [{"x": -0.34, "y": 0.03, "scale": 0.65}, {"x": -0.12, "y": -0.05, "scale": 0.65},
        {"x": 0.12, "y": -0.05, "scale": 0.65}, {"x": 0.34, "y": 0.03, "scale": 0.65}],
}

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
                raw = json.loads(CONTENT_PATH.read_text(encoding="utf-8"))
                data = raw.get("formations", {}) if isinstance(raw, dict) else {}
            except (ValueError, OSError):
                data = {}
        _cache = data if isinstance(data, dict) else {}
        _cache_mtime = mtime
    return _cache


def _clean(slots) -> list[dict]:
    out = []
    for s in slots or []:
        try:
            out.append({"x": float(s.get("x", 0)), "y": float(s.get("y", 0)),
                        "scale": max(0.1, float(s.get("scale", 1)))})
        except (TypeError, ValueError, AttributeError):
            continue
    return out


def get_formation(key: str | None, n: int) -> list[dict]:
    """Les n emplacements de la formation `key` (sinon ceux par défaut)."""
    n = max(SIZES[0], min(SIZES[-1], int(n)))
    slots = _clean((_load().get(key or "") or {}).get(str(n)))
    if len(slots) == n:
        return slots
    return [dict(s) for s in DEFAULT_FORMATIONS[n]]


def is_custom(key: str | None, n: int) -> bool:
    return len(_clean((_load().get(key or "") or {}).get(str(n)))) == n


def all_formations() -> dict:
    return dict(_load())


def reload_cache() -> None:
    global _cache
    _cache = None
