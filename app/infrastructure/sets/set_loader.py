"""Loader des définitions de panoplies (sets) — pattern identique à
title_loader / skill_tree_loader. Charge `sets.json` une seule fois et
le garde en cache module-level.

Format en mémoire :
    {
        "iron": {
            "name": "Acier",
            "description": "...",
            "icon": "🛡️",
            "color": "#9aa0aa",
            "tiers": [
                {"min_pieces": 2, "type": "defense_flat", "value": 1},
                ...
            ],
        },
        ...
    }
"""

from __future__ import annotations

import json
from pathlib import Path


CONTENT_PATH = (
    Path(__file__).resolve().parents[2]
    / "infrastructure"
    / "content"
    / "sets.json"
)


_cache: dict[str, dict] | None = None


def _load() -> dict[str, dict]:
    with CONTENT_PATH.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def list_definitions() -> dict[str, dict]:
    global _cache
    if _cache is None:
        _cache = _load()
    return _cache


def get_definition(family: str) -> dict | None:
    return list_definitions().get(family)


def clear_cache() -> None:
    global _cache
    _cache = None
