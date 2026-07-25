"""Poids de spawn élémentaires PAR MONSTRE (défini à la fiche du monstre).

Chaque monstre répartit son spawn parmi les éléments de sa zone : plus le poids
d'un élément est grand, plus il a de chances de spawner sous cet élément. Un
poids de 0 (ou élément absent) = le monstre ne spawne jamais sous cet élément.

    weights[mob_code][element] = int (>0)

Un monstre SANS aucun poids défini hérite d'un tirage **uniforme** sur les
éléments de sa zone (voir `element_spot_resolver`). Source de vérité :
`content/mob_element_weights.json`. Cache invalidé par mtime → une édition via
l'admin est prise en compte au prochain spawn SANS redémarrage du bot.
"""

from __future__ import annotations

import json
from pathlib import Path

CONTENT_PATH = Path(__file__).resolve().parents[1] / "content" / "mob_element_weights.json"

_cache: dict | None = None
_cache_mtime: float | None = None


def _load() -> dict:
    global _cache, _cache_mtime
    try:
        mtime = CONTENT_PATH.stat().st_mtime
    except OSError:
        mtime = None
    if _cache is None or mtime != _cache_mtime:
        data: dict = {}
        if CONTENT_PATH.exists():
            try:
                with CONTENT_PATH.open("r", encoding="utf-8") as fh:
                    raw = json.load(fh)
                data = raw.get("weights", {}) if isinstance(raw, dict) else {}
            except (ValueError, OSError):
                data = {}
        _cache = data if isinstance(data, dict) else {}
        _cache_mtime = mtime
    return _cache


def get_weights(mob_code: str | None) -> dict[str, int]:
    """Poids par élément (>0 uniquement) pour ce monstre. Vide → hérite d'un
    tirage uniforme sur les éléments de sa zone."""
    if not mob_code:
        return {}
    raw = _load().get(mob_code)
    if not isinstance(raw, dict):
        return {}
    out: dict[str, int] = {}
    for elem, w in raw.items():
        try:
            wi = max(0, int(w))
        except (TypeError, ValueError):
            wi = 0
        if wi > 0:
            out[str(elem).strip().lower()] = wi
    return out


def all_weights() -> dict:
    return dict(_load())


def reload_cache() -> None:
    global _cache, _cache_mtime
    _cache = None
    _cache_mtime = None
