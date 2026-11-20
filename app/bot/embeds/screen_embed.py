"""Un écran dessiné (`rendering/screens.py`) emballé pour Discord : l'embed qui
porte l'image et son fichier. None si le rendu échoue — l'appelant garde alors
son embed texte (jamais d'écran vide pour une image ratée)."""

from __future__ import annotations

import logging
from collections.abc import Callable

import discord

from app.shared.paths import GENERATED_PROFILES_DIR

_logger = logging.getLogger(__name__)


def image_embed(compose: Callable, stem: str, color: discord.Color, **kwargs) -> tuple[discord.Embed, discord.File] | None:
    """À appeler dans un thread : Pillow bloquerait le bot."""
    try:
        GENERATED_PROFILES_DIR.mkdir(parents=True, exist_ok=True)
        filename = f"{stem}.png"
        path = GENERATED_PROFILES_DIR / filename
        compose(str(path), **kwargs)
        embed = discord.Embed(color=color)
        embed.set_image(url=f"attachment://{filename}")
        return embed, discord.File(str(path), filename=filename)
    except Exception:  # noqa: BLE001
        _logger.exception("rendu de l'écran %s en échec : repli sur le texte", stem)
        return None
