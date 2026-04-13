from pathlib import Path
import discord

from app.shared.paths import ASSETS_DIR


def build_encounter_embed(
    mob_name: str,
    state_text: str,
    image_name: str | None = None,
) -> tuple[discord.Embed, discord.File | None]:

    embed = discord.Embed(
        title=f"👾 {mob_name}",
        description=state_text,
        color=discord.Color.dark_red(),
    )

    file = None

    if image_name is not None:
        image_path = ASSETS_DIR / image_name

        if image_path.exists():
            # IMPORTANT: Discord n'accepte pas les "/" dans filename
            filename = Path(image_name).name

            file = discord.File(image_path, filename=filename)
            embed.set_image(url=f"attachment://{filename}")
        else:
            # fallback silencieux (important pour éviter crash en prod)
            print(f"[WARN] Image not found: {image_path}")

    return embed, file