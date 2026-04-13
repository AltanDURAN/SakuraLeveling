from pathlib import Path
import discord

BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent

def build_encounter_embed(
    mob_name: str,
    state_text: str,
    image_name: str | None = None,
) -> discord.Embed:
    embed = discord.Embed(
        title=f"👾 {mob_name}",
        description=state_text,
        color=discord.Color.dark_red(),
    )

    if image_name is not None:
        image_path = BASE_DIR / "assets" / image_name
        file = discord.File(image_path, filename=image_name)
        embed.set_image(url=f"attachment://{image_name}")

    return embed, file