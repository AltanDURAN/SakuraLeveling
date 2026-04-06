import discord


def build_encounter_embed(
    mob_name: str,
    image_url: str | None,
    participant_count: int,
    state_text: str,
) -> discord.Embed:
    embed = discord.Embed(
        title=f"👾 {mob_name}",
        description=state_text,
        color=discord.Color.dark_red(),
    )

    embed.add_field(
        name="👥 Aventuriers",
        value=str(participant_count),
        inline=True,
    )

    if image_url:
        embed.set_image(url=image_url)

    return embed