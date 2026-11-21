"""Couleurs du site admin partagées entre les pages (audit des duplications,
21/11/2026) : une rareté ajoutée ou recolorée l'est partout à la fois."""

from __future__ import annotations

#: Pastilles de rareté du site (palette du site, plus douce que celle du bot).
RARITY_HEX: dict[str, str] = {
    "common": "#9aa0aa", "uncommon": "#3fb950", "rare": "#4a9eff",
    "epic": "#a371f7", "legendary": "#e3b341", "mythic": "#eb465a",
}


def hex_color(rgb, default: str = "#96969b") -> str:
    """(r, g, b) → « #rrggbb »."""
    try:
        r, g, b = rgb[:3]
        return f"#{int(r):02x}{int(g):02x}{int(b):02x}"
    except (TypeError, ValueError):
        return default
