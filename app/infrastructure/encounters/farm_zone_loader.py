"""Zones de farm : résout le salon de spawn d'un mob selon sa famille.

Chaque salon Discord représente une zone de farm. Les familles non mappées
tombent sur le salon par défaut (zone de base). Cache module-level ; contenu
dans `content/farm_zones.json`.

À terme : l'accès aux zones avancées sera conditionné à un pass de la guilde
des aventuriers (rang D, C, ...). La zone de base (slime + gobelin) reste
accessible à tous.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.infrastructure.config.settings import settings

CONTENT_PATH = Path(__file__).resolve().parents[1] / "content" / "farm_zones.json"

_cache: dict | None = None


def _load() -> dict:
    global _cache
    if _cache is None:
        if CONTENT_PATH.exists():
            with CONTENT_PATH.open("r", encoding="utf-8") as fh:
                _cache = json.load(fh)
        else:
            _cache = {}
    return _cache


def default_channel_id() -> int:
    """Salon de la zone de base. Fallback sur encounter_channel_id si non défini."""
    data = _load()
    ch = int(data.get("default_channel_id", 0) or 0)
    return ch or settings.encounter_channel_id


def default_background() -> str:
    return _load().get("default_background", "clairiere_sinistre.png")


def _zone(family: str | None) -> dict | None:
    """Entrée de zone d'une famille, normalisée en dict {channel_id, background}.
    Rétrocompatible avec l'ancien format (valeur = int channel_id)."""
    if not family:
        return None
    z = (_load().get("zones", {}) or {}).get(family)
    if z is None:
        return None
    if isinstance(z, int):  # ancien format
        return {"channel_id": z, "background": default_background()}
    return z


def get_spawn_channel_for_family(family: str | None) -> int:
    """Salon de spawn pour la famille (zone de base si non mappée ou channel_id=0
    = zone pas encore configurée)."""
    z = _zone(family)
    if z:
        ch = int(z.get("channel_id", 0) or 0)
        if ch:
            return ch
    return default_channel_id()


def get_background_for_family(family: str | None) -> str:
    """Nom du décor (dans assets/landscapes/) pour la famille. Décor par défaut
    si la zone n'est pas encore configurée (channel_id=0)."""
    z = _zone(family)
    if z and int(z.get("channel_id", 0) or 0):
        return z.get("background") or default_background()
    return default_background()


def clear_cache() -> None:
    global _cache
    _cache = None
