from pathlib import Path
import discord

BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent
print("''''''''''''''''''''''")
print(BASE_DIR)
print("''''''''''''''''''''''")

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

    print("mob_name : ", mob_name)
    print("state_text : ", state_text)
    print("image_name : ", image_name)
    if image_name is not None:
        image_path = BASE_DIR / "assets" / image_name
        print(image_path)
        print(image_path)
        print(image_path)
        print(image_path)
        file = discord.File(image_path, filename=image_name)
        embed.set_image(url=f"attachment://{image_name}")

    return embed, file