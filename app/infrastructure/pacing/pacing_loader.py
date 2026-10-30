"""Rythme du jeu (`pacing.json`) : apparitions de zone et rendez-vous du raid.

Cache invalidé par la date de modification du fichier : une édition depuis
l'admin web est prise en compte par le bot sans redémarrage.
"""

from __future__ import annotations

import json
from dataclasses import fields
from pathlib import Path

from app.domain.services.lunar_service import DEFAULT_RULES as DEFAULT_LUNAR_RULES
from app.domain.services.lunar_service import LunarRule
from app.domain.services.pacing_service import DEFAULT, Pacing, RaidPacing, ZoneOverride, ZonePacing

CONTENT_PATH = Path(__file__).resolve().parents[1] / "content" / "pacing.json"

_cache: Pacing | None = None
_cache_mtime: float | None = None


def _build(cls, raw: dict, default):
    values = {}
    for f in fields(cls):
        value = raw.get(f.name, getattr(default, f.name))
        if value is not None:
            kind = type(getattr(default, f.name))
            value = kind(value) if kind in (int, float, bool) else value
        values[f.name] = value
    return cls(**values)


def parse(data: dict) -> Pacing:
    """Le contenu de `pacing.json` (valeurs manquantes = défaut)."""
    overrides = {}
    for channel_id, raw in (data.get("zone_overrides") or {}).items():
        overrides[int(channel_id)] = ZoneOverride(
            paused=bool(raw.get("paused", False)),
            respawn_min_minutes=None if raw.get("respawn_min_minutes") is None
            else float(raw["respawn_min_minutes"]),
            respawn_max_minutes=None if raw.get("respawn_max_minutes") is None
            else float(raw["respawn_max_minutes"]),
        )
    raw_lunar = data.get("lunar") or {}
    lunar = {code: _build(LunarRule, raw_lunar.get(code) or {}, default)
             for code, default in DEFAULT_LUNAR_RULES.items()}
    return Pacing(zones=_build(ZonePacing, data.get("zones") or {}, DEFAULT.zones),
                  overrides=overrides,
                  raid=_build(RaidPacing, data.get("raid") or {}, DEFAULT.raid),
                  lunar=lunar)


def get_pacing() -> Pacing:
    global _cache, _cache_mtime
    try:
        mtime = CONTENT_PATH.stat().st_mtime
    except OSError:
        mtime = None
    if _cache is None or mtime != _cache_mtime:
        data: dict = {}
        if CONTENT_PATH.exists():
            try:
                data = json.loads(CONTENT_PATH.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                data = {}
        _cache, _cache_mtime = parse(data), mtime
    return _cache


def clear_cache() -> None:
    global _cache
    _cache = None
