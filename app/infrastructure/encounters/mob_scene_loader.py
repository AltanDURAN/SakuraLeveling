"""Composition de la scène de spawn, par monstre.

Chaque monstre peut avoir sa propre mise en scène, composée à la main dans
l'admin web (Monde › Scènes) : quelle portion de l'image d'environnement est
visible, et où/à quelle taille le monstre est posé dedans.

Tout est stocké en **fractions (0-1)** → la composition reste valide si on
change la taille du cadre Discord ou si on remplace une image d'environnement
par une version de résolution différente.

Schéma d'une entrée (clé = code du monstre) :
    {
      "background": "clairiere_sinistre.png",   # asset dans assets/landscapes/
      "crop": {"x": 0.30, "y": 0.18, "w": 0.42},  # portion visible du décor
      "mob":  {"x": 0.50, "y": 0.88, "scale": 0.62},  # centre-x, pieds, hauteur
      "shadow": true
    }

Cache invalidé par mtime → une édition via l'admin est prise en compte au
prochain spawn, sans redémarrer le bot.
"""

from __future__ import annotations

import json
from pathlib import Path

CONTENT_PATH = Path(__file__).resolve().parents[1] / "content" / "mob_scenes.json"

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
                data = raw.get("scenes", {}) if isinstance(raw, dict) else {}
            except (ValueError, OSError):
                data = {}
        _cache = data if isinstance(data, dict) else {}
        _cache_mtime = mtime
    return _cache


def all_scenes() -> dict:
    """Toutes les compositions (copie)."""
    return dict(_load())


def get_mob_scene(mob_code: str | None) -> dict | None:
    """Composition d'un monstre, ou None s'il n'en a pas (→ rendu auto)."""
    if not mob_code:
        return None
    scene = _load().get(mob_code)
    return scene if isinstance(scene, dict) else None


def reload_cache() -> None:
    global _cache, _cache_mtime
    _cache = None
    _cache_mtime = None
