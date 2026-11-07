"""Règlement du serveur (`rules.json`).

Cache invalidé par la date de modification du fichier. Le panneau du salon
du règlement n'est réécrit qu'au démarrage du bot (déploiement).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from app.domain.services.rules_service import RuleSection, Rules

CONTENT_PATH = Path(__file__).resolve().parents[1] / "content" / "rules.json"

_logger = logging.getLogger(__name__)
_cache: Rules | None = None
_cache_mtime: float | None = None


def parse(data: dict) -> Rules:
    sections = tuple(
        RuleSection(emoji=str(raw.get("emoji", "")), title=str(raw.get("title", "")),
                    rules=tuple(str(rule) for rule in raw.get("rules") or ()))
        for raw in data.get("sections") or ()
    )
    return Rules(version=int(data.get("version", 1)), updated=str(data.get("updated", "")),
                 title=str(data.get("title", "Règlement")), intro=str(data.get("intro", "")),
                 sections=sections, footer=str(data.get("footer", "")))


def get_rules() -> Rules:
    global _cache, _cache_mtime
    try:
        mtime = CONTENT_PATH.stat().st_mtime
    except OSError:
        mtime = None
    if _cache is None or mtime != _cache_mtime:
        try:
            data = json.loads(CONTENT_PATH.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            # Un fichier illisible ne doit pas ouvrir le jeu sans règlement :
            # on garde la dernière version lue.
            _logger.exception("rules.json illisible")
            if _cache is not None:
                return _cache
            data = {}
        _cache, _cache_mtime = parse(data), mtime
    return _cache


def clear_cache() -> None:
    global _cache
    _cache = None
