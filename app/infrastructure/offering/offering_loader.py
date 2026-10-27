"""Offrande commune (`offering.json`) : paramètres du prix et divinités.

Cache invalidé par la date de modification du fichier : une édition depuis
l'admin web est prise en compte par le bot sans redémarrage.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.domain.services.offering_service import DEFAULT_PARAMS, Deity, OfferingParams

CONTENT_PATH = Path(__file__).resolve().parents[1] / "content" / "offering.json"

_cache: tuple[OfferingParams, list[Deity]] | None = None
_cache_mtime: float | None = None


def _load() -> tuple[OfferingParams, list[Deity]]:
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
        raw = data.get("params") or {}
        params = OfferingParams(
            base_target=int(raw.get("base_target", DEFAULT_PARAMS.base_target)),
            step_per_fill=int(raw.get("step_per_fill", DEFAULT_PARAMS.step_per_fill)),
            growth_pct=float(raw.get("growth_pct", DEFAULT_PARAMS.growth_pct)),
            decay_pct=float(raw.get("decay_pct", DEFAULT_PARAMS.decay_pct)),
            blessing_hours=int(raw.get("blessing_hours", DEFAULT_PARAMS.blessing_hours)),
        )
        deities = [Deity(code=d["code"], name=d["name"], title=d.get("title", ""), emoji=d.get("emoji", "✨"),
                         effect=d["effect"], value=float(d.get("value", 0)), blessing=d.get("blessing", ""))
                   for d in data.get("deities", [])]
        _cache, _cache_mtime = (params, deities), mtime
    return _cache


def get_params() -> OfferingParams:
    return _load()[0]


def list_deities() -> list[Deity]:
    return _load()[1]


def get_deity(code: str | None) -> Deity | None:
    return next((d for d in list_deities() if d.code == code), None)


def clear_cache() -> None:
    global _cache
    _cache = None
