import discord

from app.domain.entities.shop_item import ShopItem
from app.domain.services.shop_pricing_service import ShopPricingService


def _format_int(value: int) -> str:
    return f"{value:,}".replace(",", " ")


def build_shop_embed(shop_items: list[ShopItem]) -> discord.Embed:
    embed = discord.Embed(
        title="🏪 Boutique",
        color=discord.Color.gold(),
    )

    enabled_items = [item for item in shop_items if item.enabled]

    if not enabled_items:
        embed.description = (
            "La boutique est vide pour le moment. "
            "Demandez à un admin d'y ajouter des articles."
        )
        return embed

    pricing_service = ShopPricingService()

    for shop_item in enabled_items:
        item_def = shop_item.item_definition
        current_sell = pricing_service.current_sell_price(shop_item)

        if shop_item.stock_threshold > 0:
            saturation = min(100, round(100 * shop_item.current_stock / shop_item.stock_threshold))
        else:
            saturation = 0

        sell_range = (
            f"{shop_item.min_sell_price}–{shop_item.max_sell_price}"
            if shop_item.max_sell_price != shop_item.min_sell_price
            else f"{shop_item.max_sell_price}"
        )

        lines = [
            f"💰 Acheter : **{_format_int(shop_item.buy_price)}** or / unité",
            f"💵 Vendre : **{_format_int(current_sell)}** or / unité (plage {sell_range})",
            f"📦 Stock du shop : **{shop_item.current_stock}** "
            f"({saturation}% de saturation)",
        ]

        embed.add_field(
            name=f"📦 {item_def.name} (`{item_def.code}`)",
            value="\n".join(lines),
            inline=False,
        )

    embed.set_footer(
        text="Utilisez /buy <item> <qté> pour acheter, /sell <item> <qté> pour vendre."
    )
    return embed


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


def build_sell_result_embed(
    success: bool,
    message: str,
    total_gain: int,
    item_name: str,
    quantity: int,
) -> discord.Embed:
    color = discord.Color.green() if success else discord.Color.red()
    embed = discord.Embed(
        title="💸 Vente" if success else "❌ Vente refusée",
        description=message,
        color=color,
    )
    if success:
        embed.add_field(name="Objet", value=f"{quantity}× {item_name}", inline=True)
        embed.add_field(name="Gain", value=f"{_format_int(total_gain)} or", inline=True)
    return embed
