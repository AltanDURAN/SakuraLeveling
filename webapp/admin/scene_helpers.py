"""Helpers partagés par les éditeurs de scène (spot dans ZONES, placement dans
SCÈNES). Évite la duplication : cadrage du décor, joueurs de démo, lecture des
paramètres en fractions, liste des décors disponibles."""

from __future__ import annotations

from pathlib import Path

from app.shared.paths import LANDSCAPES_ASSETS_DIR


def safe(name: str) -> str:
    """Nom de fichier sans composante de chemin (anti path-traversal)."""
    return Path(name or "").name


def fnum(params, key: str, default: float) -> float:
    try:
        return float(params.get(key, default))
    except (TypeError, ValueError):
        return default


def truthy(value, default: bool = True) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() not in {"0", "false", "off", "no", ""}


def list_backgrounds() -> list[str]:
    if not LANDSCAPES_ASSETS_DIR.exists():
        return []
    return sorted(
        p.name for p in LANDSCAPES_ASSETS_DIR.iterdir()
        if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".gif"}
    )


def demo_players() -> list[dict]:
    """Trois joueurs d'exemple (PV variés) pour juger les bandeaux du HUD."""
    return [
        {"name": "Altan", "avatar_url": None, "current_hp": 100, "max_hp": 100},
        {"name": "Kaori", "avatar_url": None, "current_hp": 55, "max_hp": 100},
        {"name": "Rin", "avatar_url": None, "current_hp": 22, "max_hp": 100},
    ]
