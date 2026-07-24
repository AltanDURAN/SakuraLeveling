"""Scènes de spawn composées par monstre et par élément.

Chaque monstre définit, pour chaque élément qu'il peut prendre, une scène
complète : fond + cadrage du fond (crop/zoom) + placement du monstre (position,
taille) + ombre + poids de spawn + fenêtre horaire (jour/nuit).

L'élément de spawn est tiré parmi les scènes du monstre disponibles à l'heure
courante, pondéré par leur `weight`. Un monstre sans scène → rendu automatique
(l'appelant retombe sur le fond de zone + un tirage global d'élément).

Cache invalidé par mtime → une édition via l'admin prend effet au prochain
spawn sans redémarrer le bot.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

CONTENT_PATH = Path(__file__).resolve().parents[1] / "content" / "mob_scenes.json"
_PARIS = ZoneInfo("Europe/Paris")

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
                data = raw.get("scenes", {}) if isinstance(raw, dict) else {}
            except (ValueError, OSError):
                data = {}
        _cache = data if isinstance(data, dict) else {}
        _cache_mtime = mtime
    return _cache


def _is_day(now: datetime | None = None) -> bool:
    now = now or datetime.now(_PARIS)
    if now.tzinfo is None:
        now = now.replace(tzinfo=_PARIS)
    return 6 <= now.astimezone(_PARIS).hour < 18


def _time_ok(time_window: str, day: bool) -> bool:
    tw = (time_window or "always").strip().lower()
    if tw == "day":
        return day
    if tw == "night":
        return not day
    return True


def all_scenes() -> dict:
    return dict(_load())


def get_scenes(mob_code: str | None) -> dict:
    """Toutes les scènes (par élément) d'un monstre."""
    if not mob_code:
        return {}
    s = _load().get(mob_code)
    return dict(s) if isinstance(s, dict) else {}


def get_scene(mob_code: str | None, element: str | None) -> dict | None:
    """Scène composée d'un couple (monstre, élément), ou None."""
    if not mob_code or not element:
        return None
    s = get_scenes(mob_code).get(str(element).strip().lower())
    return s if isinstance(s, dict) else None


def pick_element(mob_code: str | None, now: datetime | None = None, rng=None) -> str | None:
    """Tire un élément parmi les scènes du monstre disponibles à l'heure courante
    (poids > 0, fenêtre horaire respectée). None si le monstre n'a aucune scène
    exploitable (→ fallback appelant)."""
    import random as _random

    scenes = get_scenes(mob_code)
    if not scenes:
        return None
    day = _is_day(now)
    elements, weights = [], []
    for elem, sc in scenes.items():
        if not isinstance(sc, dict):
            continue
        try:
            w = max(0, int(sc.get("weight", 0)))
        except (TypeError, ValueError):
            w = 0
        if w <= 0 or not _time_ok(sc.get("time", "always"), day):
            continue
        elements.append(elem)
        weights.append(w)
    if not elements:
        return None
    return (rng or _random).choices(elements, weights=weights, k=1)[0]


def reload_cache() -> None:
    global _cache, _cache_mtime
    _cache = None
    _cache_mtime = None
