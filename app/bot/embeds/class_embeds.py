import discord

from app.domain.entities.class_definition import ClassDefinition


def build_player_class_embed(
    display_name: str,
    active_class: ClassDefinition | None,
) -> discord.Embed:
    embed = discord.Embed(
        title=f"🧬 Classe de {display_name}",
        color=discord.Color.gold(),
    )

    if active_class is None:
        embed.description = "Aucune classe active."
        return embed

    embed.add_field(name="Nom", value=active_class.name, inline=False)
    embed.add_field(name="Description", value=active_class.description, inline=False)

    bonuses = active_class.stat_bonuses or {}
    if bonuses:
        bonus_lines = [f"{key}: +{value}" for key, value in bonuses.items()]
        embed.add_field(name="Bonus", value="\n".join(bonus_lines), inline=False)

    return embed