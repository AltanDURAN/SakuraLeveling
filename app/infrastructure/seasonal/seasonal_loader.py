"""Événements saisonniers (`seasonal_events.json`) : calendrier de l'Avent,
Noël, objets d'événement, boutiques d'événement, Nouvel An.

Cache invalidé par la date de modification du fichier : une édition depuis
le site est prise en compte par le bot sans redémarrage. Un fichier illisible
donne un contenu vide (aucun événement) plutôt qu'une panne.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from app.domain.services.seasonal_service import SeasonalContent, parse_content

CONTENT_PATH = Path(__file__).resolve().parents[1] / "content" / "seasonal_events.json"

_logger = logging.getLogger(__name__)
_cache: SeasonalContent | None = None
_raw: dict = {}
_cache_mtime: float | None = None


def _load() -> SeasonalContent:
    global _cache, _raw, _cache_mtime
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
                _logger.exception("seasonal_events.json illisible : aucun événement saisonnier")
                data = {}
        _raw = data if isinstance(data, dict) else {}
        _cache = parse_content(_raw)
        for problem in _cache.problems:
            _logger.warning("événements saisonniers : %s", problem)
        _cache_mtime = mtime
    return _cache


def clear_cache() -> None:
    global _cache, _raw, _cache_mtime
    _cache = None
    _raw = {}
    _cache_mtime = None


def get_content() -> SeasonalContent:
    return _load()


def raw() -> dict:
    """Le JSON tel qu'il est écrit (site admin)."""
    _load()
    return json.loads(json.dumps(_raw))
