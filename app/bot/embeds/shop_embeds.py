import discord

from app.shared.formatters import format_int as _format_int


def build_buy_result_embed(
    success: bool,
    message: str,
    total_cost: int,
    item_name: str,
    quantity: int,
) -> discord.Embed:
    color = discord.Color.green() if success else discord.Color.red()
    embed = discord.Embed(
        title="🛒 Achat" if success else "❌ Achat refusé",
        description=message,
        color=color,
    )
    if success:
        embed.add_field(name="Objet", value=f"{quantity}× {item_name}", inline=True)
        embed.add_field(name="Coût", value=f"{_format_int(total_cost)} or", inline=True)
    return embed
