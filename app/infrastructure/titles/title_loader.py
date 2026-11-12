"""Loader des définitions de titres : cache relu dès que `titles.json`
change (site admin, 11/11/2026) — comme `boss_definition_loader`."""

import json
from pathlib import Path

from app.domain.entities.title_definition import TitleDefinition


CONTENT_PATH = (
    Path(__file__).resolve().parents[2]
    / "infrastructure"
    / "content"
    / "titles.json"
)


_cache: list[TitleDefinition] | None = None
_cache_mtime: float | None = None


def _load() -> list[TitleDefinition]:
    with CONTENT_PATH.open("r", encoding="utf-8") as fh:
        raw = json.load(fh)
    return [
        TitleDefinition(
            code=item["code"],
            name=item["name"],
            description=item.get("description", ""),
            icon=item.get("icon", "🏷️"),
            condition_type=item["condition_type"],
            condition_target=item.get("condition_target", ""),
            condition_value=int(item.get("condition_value", 0)),
            exclusive=bool(item.get("exclusive", False)),
            effects=item.get("effects", []) or [],
        )
        for item in raw
    ]


def _mtime() -> float | None:
    try:
        return CONTENT_PATH.stat().st_mtime
    except OSError:
        return None


def list_definitions() -> list[TitleDefinition]:
    """Relu dès que le fichier change (site admin) : sans redémarrer le bot."""
    global _cache, _cache_mtime
    mtime = _mtime()
    if _cache is None or mtime != _cache_mtime:
        _cache = _load()
        _cache_mtime = mtime
    return _cache


def get_definition(code: str) -> TitleDefinition | None:
    for d in list_definitions():
        if d.code == code:
            return d
    return None


def list_for_condition(condition_type: str) -> list[TitleDefinition]:
    """Filtre les titres dont la condition correspond au type donné.
    Utilisé pour ne checker que les titres pertinents lors d'un évènement
    (ex : un kill_family ne doit pas re-vérifier les titres de la semaine)."""
    return [d for d in list_definitions() if d.condition_type == condition_type]


def clear_cache() -> None:
    global _cache, _cache_mtime
    _cache = None
    _cache_mtime = None
