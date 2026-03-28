import discord

from app.domain.entities.player_inventory_item import PlayerInventoryItem


def build_inventory_embed(
    display_name: str,
    items: list[PlayerInventoryItem],
) -> discord.Embed:
    embed = discord.Embed(
        title=f"🎒 Inventaire de {display_name}",
        color=discord.Color.green(),
    )

    if not items:
        embed.description = "Votre inventaire est vide."
        return embed

    lines = [
        f"{item.item_definition.name} x{item.quantity}"
        for item in items
    ]
    embed.description = "\n".join(lines)
    return embed