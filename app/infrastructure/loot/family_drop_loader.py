"""Charge le drop de famille (ressource garantie) par famille.

Chaque famille de mob a UNE ressource commune (ex : gobelin → gobelin_tooth).
Chaque MEMBRE de la famille lâche cette ressource à chaque kill (drop GARANTI),
en quantité tirée dans un [min,max] propre à ce monstre (ex : gobelin 1-2,
gobelin géant 2-4). Cache invalidé par mtime → une édition via l'admin est
prise en compte au prochain kill SANS redémarrage.

Format de family_drops.json :
    { "<famille>": {
        "item_code": "<ressource>",
        "mobs": { "<mob_code>": {"min": 1, "max": 2}, ... }
      }, ... }
"""

from __future__ import annotations

import json
from pathlib import Path

_CONTENT = Path(__file__).resolve().parents[1] / "content" / "family_drops.json"
_cache: dict[str, dict] | None = None
_cache_mtime: float | None = None


def get_family_drops() -> dict[str, dict]:
    """Renvoie le mapping famille → {item_code, mobs:{code:{min,max}}}."""
    global _cache, _cache_mtime
    try:
        mtime = _CONTENT.stat().st_mtime
    except OSError:
        mtime = None
    if _cache is None or mtime != _cache_mtime:
        data: dict = {}
        if _CONTENT.exists():
            try:
                with open(_CONTENT, encoding="utf-8") as f:
                    data = json.load(f)
            except (ValueError, OSError):
                data = {}
        _cache = data if isinstance(data, dict) else {}
        _cache_mtime = mtime
    return _cache


def clear_cache() -> None:
    global _cache, _cache_mtime
    _cache = None
    _cache_mtime = None
