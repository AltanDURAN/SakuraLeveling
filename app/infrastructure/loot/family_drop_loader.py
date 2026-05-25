"""Charge le drop commun par famille (cache module-level).

Chaque famille de mob a ≥1 drop commun partagé par tous ses membres (ex :
gobelin → gobelin_tooth). Défini une seule fois ici, plutôt que dupliqué dans
chaque mob. La quantité droppée croît avec la puissance du mob (cf. LootService).

Format de family_drops.json :
    { "<famille>": { "item_code": "...", "drop_rate": 0.75 }, ... }
"""

from __future__ import annotations

import json
from pathlib import Path

_CONTENT = Path(__file__).resolve().parents[1] / "content" / "family_drops.json"
_cache: dict[str, dict] | None = None


def get_family_drops() -> dict[str, dict]:
    """Renvoie le mapping famille → {item_code, drop_rate}. Mis en cache."""
    global _cache
    if _cache is None:
        if _CONTENT.exists():
            with open(_CONTENT, encoding="utf-8") as f:
                _cache = json.load(f)
        else:
            _cache = {}
    return _cache
