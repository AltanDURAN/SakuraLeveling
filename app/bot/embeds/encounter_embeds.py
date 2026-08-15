import logging
from pathlib import Path

import discord

from app.shared.paths import ASSETS_DIR

_logger = logging.getLogger(__name__)


def build_encounter_embed(
    image_name: str | None = None,
) -> tuple[discord.Embed, discord.File | None]:
    embed = discord.Embed(color=discord.Color.dark_red())
    file = None

    if image_name is not None:
        image_path = ASSETS_DIR / image_name

        if image_path.exists():
            filename = Path(image_name).name
            file = discord.File(image_path, filename=filename)
            embed.set_image(url=f"attachment://{filename}")
        else:
            _logger.warning("Image d'encounter introuvable : %s", image_path)

    return embed, file