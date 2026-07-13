"""Zones de farm : résout le salon de spawn d'un mob selon sa famille.

Chaque zone de farm = un salon Discord + une ou plusieurs FAMILLES de mobs qui
y spawnent + un décor + une fourchette d'essences droppées par kill. Les
familles non mappées tombent sur la zone de base (défaut). Cache module-level ;
contenu dans `content/farm_zones.json`.

Format canonique (zone-centré) — édité par l'admin web :
    {
      "default_channel_id": ..., "default_background": "...",
      "default_essences_min": 1, "default_essences_max": 1,
      "zones": [
        {"name": "Clairière sinistre", "channel_id": 123, "families": ["slime","gobelin"],
         "background": "clairiere_sinistre.png", "essences_min": 1, "essences_max": 1},
        ...
      ]
    }

Rétrocompatible avec l'ANCIEN format où `zones` était un dict `{famille: {...}}`.

À terme : l'accès aux zones avancées sera conditionné à un pass de la guilde
des aventuriers (rang D, C, ...). La zone de base reste accessible à tous.
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


def list_zones() -> list[dict]:
    """Zones NORMALISÉES en liste de dicts {name, channel_id, families[],
    background, essences_min, essences_max}. Gère les deux formats de JSON."""
    data = _load()
    raw = data.get("zones", [])
    zones: list[dict] = []
    dmin, dmax = default_essences_range()

    if isinstance(raw, dict):
        # ANCIEN format : {famille: {channel_id, background, essences_*}}.
        # On regroupe les familles partageant le même channel_id en une zone.
        by_channel: dict[int, dict] = {}
        for family, entry in raw.items():
            if isinstance(entry, int):  # très ancien format (valeur = channel_id)
                entry = {"channel_id": entry}
            ch = int((entry or {}).get("channel_id", 0) or 0)
            lo, hi = _essences_range_from_entry(entry or {}, dmin, dmax)
            z = by_channel.setdefault(ch, {
                "name": (entry or {}).get("name", ""),
                "channel_id": ch,
                "families": [],
                "background": (entry or {}).get("background") or default_background(),
                "essences_min": lo,
                "essences_max": hi,
            })
            if family and family not in z["families"]:
                z["families"].append(family)
        zones = list(by_channel.values())
    else:
        for entry in raw or []:
            entry = entry or {}
            lo, hi = _essences_range_from_entry(entry, dmin, dmax)
            zones.append({
                "name": entry.get("name", ""),
                "channel_id": int(entry.get("channel_id", 0) or 0),
                "families": [f for f in (entry.get("families") or []) if f],
                "background": entry.get("background") or default_background(),
                "essences_min": lo,
                "essences_max": hi,
            })
    return zones


def _zone_for_family(family: str | None) -> dict | None:
    """Zone (normalisée) qui contient la famille, ou None si non mappée."""
    if not family:
        return None
    for z in list_zones():
        if family in z["families"] and int(z.get("channel_id", 0) or 0):
            return z
    return None


def get_spawn_channel_for_family(family: str | None) -> int:
    """Salon de spawn pour la famille (zone de base si non mappée ou channel_id=0
    = zone pas encore configurée)."""
    z = _zone_for_family(family)
    if z:
        ch = int(z.get("channel_id", 0) or 0)
        if ch:
            return ch
    return default_channel_id()


def get_background_for_family(family: str | None) -> str:
    """Nom du décor (dans assets/landscapes/) pour la famille. Décor par défaut
    si la zone n'est pas configurée OU si l'image du décor n'existe pas encore
    (anti-crash : on retombe sur le décor par défaut jusqu'à l'ajout)."""
    z = _zone_for_family(family)
    if z:
        bg = z.get("background") or default_background()
        from app.shared.paths import LANDSCAPES_ASSETS_DIR
        if (LANDSCAPES_ASSETS_DIR / bg).exists():
            return bg
    return default_background()


def _essences_range_from_entry(entry: dict, dmin: int, dmax: int) -> tuple[int, int]:
    """Extrait (min, max) d'essences d'une entrée de zone. Supporte le nouveau
    format `essences_min`/`essences_max` ET l'ancien `essences_per_kill` (fixe)."""
    if "essences_min" in entry or "essences_max" in entry:
        lo = int(entry.get("essences_min", 1) or 0)
        hi = int(entry.get("essences_max", entry.get("essences_min", 1)) or 0)
    elif "essences_per_kill" in entry:  # ancien format = nombre fixe
        lo = hi = int(entry.get("essences_per_kill", dmax) or 0)
    else:
        lo, hi = dmin, dmax
    lo = max(0, lo)
    hi = max(lo, hi)
    return lo, hi


def default_essences_range() -> tuple[int, int]:
    data = _load()
    dmin = int(data.get("default_essences_min", data.get("default_essences_per_kill", 1)) or 0)
    dmax = int(data.get("default_essences_max", data.get("default_essences_per_kill", 1)) or 0)
    dmin = max(0, dmin)
    dmax = max(dmin, dmax)
    return dmin, dmax


def get_essences_range_for_family(family: str | None) -> tuple[int, int]:
    """Fourchette (min, max) d'essences élémentaires droppées par kill dans la
    zone de la famille (zone de base si non mappée). Le nombre effectif est tiré
    aléatoirement dans [min, max] à chaque kill. Ex : clairière 1-1, cimetière
    1-2, zone 3 1-3."""
    z = _zone_for_family(family)
    if z:
        return int(z["essences_min"]), int(z["essences_max"])
    return default_essences_range()


def list_zone_channels() -> list[int]:
    """Liste des salons de spawn DISTINCTS (les zones actives). Chaque salon =
    une zone qui tournera son propre encounter en parallèle. Inclut la zone de
    base + chaque zone configurée (channel_id != 0)."""
    channels: set[int] = set()
    base = default_channel_id()
    if base:
        channels.add(base)
    for z in list_zones():
        ch = int(z.get("channel_id", 0) or 0)
        if ch:
            channels.add(ch)
    return sorted(channels)


def clear_cache() -> None:
    global _cache
    _cache = None
