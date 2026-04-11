import discord


def build_encounter_embed(
    mob_name: str,
    image_url: str | None,
    state_text: str,
    generated_image_name: str | None = None,
) -> discord.Embed:
    embed = discord.Embed(
        title=f"👾 {mob_name}",
        description=state_text,
        color=discord.Color.dark_red(),
    )

    if generated_image_name is not None:
        embed.set_image(url=f"attachment://{generated_image_name}")
    elif image_url:
        embed.set_image(url=image_url)

    return embed