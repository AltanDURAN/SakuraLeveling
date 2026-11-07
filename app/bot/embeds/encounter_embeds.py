import logging
from pathlib import Path

import discord

from app.shared.paths import ASSETS_DIR

_logger = logging.getLogger(__name__)

#: Fiche de fuite (aussi reconnue par `scripts/purge_flee_messages.py`).
FLEE_TEXT = "Personne ne s'est présenté pour combattre."
FLEE_TITLE_START = "🌫️"


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

def build_flee_embed(encounter) -> discord.Embed:
    """Fiche d'un monstre parti sans combat : elle reste jusqu'au suivant.
    « a pris la fuite » : rien à accorder avec un monstre au féminin."""
    verb = "ont pris la fuite" if len(encounter.mobs) > 1 else "a pris la fuite"
    return discord.Embed(
        title=f"{FLEE_TITLE_START} {encounter.mob_names} {verb}",
        description=FLEE_TEXT,
        color=discord.Color.dark_grey(),
    )
