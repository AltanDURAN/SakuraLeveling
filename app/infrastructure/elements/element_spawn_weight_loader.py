"""Poids de spawn élémentaire des monstres sauvages.

Chaque monstre sauvage spawne sous un élément tiré **aléatoirement pondéré** :
plus le poids d'un élément est grand, plus il sort souvent. Table globale
éditable dans `content/element_spawn_weights.json`. Cache module-level → un
redémarrage du bot prend en compte les changements.

Les monstres à élément forcé (bosses, ou `mob.element` explicite) ne passent
PAS par ce tirage.
"""

from __future__ import annotations

import json
import random as _random
from pathlib import Path

from app.shared.enums import ALL_ELEMENTS

CONTENT_PATH = Path(__file__).resolve().parents[1] / "content" / "element_spawn_weights.json"

_ALL = [e.value for e in ALL_ELEMENTS]
_cache: dict[str, int] | None = None
_cache_mtime: float | None = None


def _load() -> dict[str, int]:
    """Charge les poids avec cache invalidé par mtime : une édition du JSON
    (ex : via l'admin web) est prise en compte au prochain spawn SANS
    redémarrage du bot."""
    global _cache, _cache_mtime
    try:
        mtime = CONTENT_PATH.stat().st_mtime
    except OSError:
        mtime = None
    if _cache is None or mtime != _cache_mtime:
        weights: dict[str, int] = {}
        if CONTENT_PATH.exists():
            with CONTENT_PATH.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
            raw = data.get("weights", data) if isinstance(data, dict) else {}
            for elem in _ALL:
                try:
                    weights[elem] = max(0, int(raw.get(elem, 0)))
                except (TypeError, ValueError):
                    weights[elem] = 0
        # Filet : si tout est à 0 (ou fichier absent), on retombe sur uniforme
        # pour ne jamais bloquer le spawn.
        if not any(weights.get(e, 0) > 0 for e in _ALL):
            weights = {e: 1 for e in _ALL}
        _cache = weights
        _cache_mtime = mtime
    return _cache


def get_spawn_weights() -> dict[str, int]:
    """Copie de la table des poids (élément → poids)."""
    return dict(_load())


def pick_random_element(rng: _random.Random | None = None) -> str:
    """Tire un élément selon les poids configurés. Renvoie le code d'élément
    (ex : "feu"). Ne renvoie jamais neutre : au moins un poids > 0 est garanti."""
    weights = _load()
    elements = [e for e in _ALL if weights.get(e, 0) > 0]
    ws = [weights[e] for e in elements]
    picker = rng or _random
    return picker.choices(elements, weights=ws, k=1)[0]


def reload_cache() -> None:
    """Invalide le cache (après édition du JSON, sans redémarrer)."""
    global _cache
    _cache = None
