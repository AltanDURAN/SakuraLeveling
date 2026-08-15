"""Config des événements non-combat (coffre, petite fille, forge sacrée).

Chaque type d'événement = une entrée dans `content/events.json` : `enabled`,
`cadence` ({times, per_days}), `image`, + params spécifiques. Cache invalidé
par mtime (comme `farm_zone_loader`) : une édition via l'admin est reflétée au
prochain rendu webapp SANS restart, mais le BOT (process séparé, orchestrateur
au boot) nécessite un restart pour prendre en compte une nouvelle cadence.
"""

from __future__ import annotations

import json
from pathlib import Path

CONTENT_PATH = (
    Path(__file__).resolve().parents[1] / "content" / "events.json"
)

# Types connus + valeurs par défaut (fusionnées avec le JSON à la lecture).
EVENT_TYPES = ("chest", "little_girl", "sacred_forge")

_DEFAULTS: dict[str, dict] = {
    "chest": {
        "enabled": False,
        "label": "Coffre au trésor",
        "cadence": {"times": 1, "per_days": 1},
        "image": "chest.png",
        "loot": [],
        # Scaling du gain selon le niveau du gagnant : mult = 1 + niveau × pct/100.
        # 0 = pas de scaling. Ex : 2 → niveau 50 = ×2, niveau 100 = ×3.
        "level_scaling_pct": 2,
    },
    "little_girl": {
        "enabled": False,
        "label": "La petite fille",
        "cadence": {"times": 1, "per_days": 1},
        "image": "little_girl.png",
        "trap_probability": 50,
        "gold_loss_per_level": 10,
        "buff_multiplier": 1.1,
        "buff_duration_hours": 3,
        "debuff_multiplier": 0.5,
        "debuff_duration_hours": 3,
        "title_chance": 10,
        "resolve_after_minutes": 5,
    },
    "sacred_forge": {
        "enabled": False,
        "label": "La forge sacrée",
        "cadence": {"times": 1, "per_days": 3},
        "image": "sacred_forge.png",
        "max_level": 10,
        "window_minutes": 5,
    },
}

_cache: dict | None = None
_cache_mtime: float | None = None


def _load_raw() -> dict:
    global _cache, _cache_mtime
    try:
        mtime = CONTENT_PATH.stat().st_mtime
    except OSError:
        mtime = None
    if _cache is None or mtime != _cache_mtime:
        if CONTENT_PATH.exists():
            with CONTENT_PATH.open("r", encoding="utf-8") as fh:
                _cache = json.load(fh)
        else:
            _cache = {}
        _cache_mtime = mtime
    return _cache or {}


def clear_cache() -> None:
    global _cache, _cache_mtime
    _cache = None
    _cache_mtime = None


def get_config(event_type: str) -> dict:
    """Config fusionnée (défauts + JSON) pour un type. dict vide si inconnu."""
    if event_type not in _DEFAULTS:
        return {}
    merged = dict(_DEFAULTS[event_type])
    merged.update(_load_raw().get(event_type, {}) or {})
    return merged


def all_configs() -> dict[str, dict]:
    return {t: get_config(t) for t in EVENT_TYPES}


def is_enabled(event_type: str) -> bool:
    return bool(get_config(event_type).get("enabled", False))


def cadence_per_hour(event_type: str) -> float:
    """Probabilité horaire de spawn dérivée de la cadence {times, per_days}.
    Ex : 1/jour → 1/24 ; 2/jour → 2/24 ; 1 tous les 3 jours → 1/72."""
    cfg = get_config(event_type)
    cad = cfg.get("cadence", {}) or {}
    times = max(0, int(cad.get("times", 0) or 0))
    per_days = max(1, int(cad.get("per_days", 1) or 1))
    if times <= 0:
        return 0.0
    return times / (per_days * 24.0)
