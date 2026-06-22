import asyncio

import discord
from discord import app_commands
from discord.ext import commands

from app.application.use_cases.buy_from_shop import BuyFromShopUseCase
from app.bot.embeds.shop_embeds import build_buy_result_embed
from app.bot.views.shop_view import ShopView
from app.domain.services.shop_pricing_service import ShopPricingService
from app.infrastructure.db.repositories.inventory_repository import InventoryRepository
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.repositories.shop_repository import ShopRepository
from app.infrastructure.db.session import get_db_session
from app.bot.cogs._mixins import BetaChannelOnlyMixin


class ShopCog(BetaChannelOnlyMixin, commands.Cog):
    """Shop joueur : consulter et acheter. La vente n'existe pas (V2) — les
    drops de mob ne se revendent pas, ils servent uniquement au craft."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="boutique", description="Affiche les articles disponibles à la boutique")
    async def shop(self, interaction: discord.Interaction) -> None:
        with get_db_session() as session:
            shop_repository = ShopRepository(session)
            shop_items = shop_repository.list_all(only_enabled=True)

        view = ShopView(shop_items)
        embed, file = await asyncio.to_thread(view.render_current)
        await interaction.response.send_message(
            embed=embed, file=file, view=view,
        )

    @app_commands.command(name="acheter", description="Acheter un objet à la boutique")
    @app_commands.describe(item_code="Code de l'objet à acheter", quantity="Quantité à acheter")
    async def buy(
        self,
        interaction: discord.Interaction,
        item_code: str,
        quantity: app_commands.Range[int, 1, 9999] = 1,
    ) -> None:
        await interaction.response.defer()

        with get_db_session() as session:
            use_case = BuyFromShopUseCase(
                player_repository=PlayerRepository(session),
                inventory_repository=InventoryRepository(session),
                shop_repository=ShopRepository(session),
                shop_pricing_service=ShopPricingService(),
            )
            result = use_case.execute(
                discord_id=interaction.user.id,
                username=interaction.user.name,
                display_name=interaction.user.display_name,
                item_code=item_code,
                quantity=quantity,
            )

        embed = build_buy_result_embed(
            success=result.success,
            message=result.message,
            total_cost=result.total_cost,
            item_name=result.item_name,
            quantity=result.quantity,
        )
        await interaction.followup.send(embed=embed, ephemeral=not result.success)

    @buy.autocomplete("item_code")
    async def shop_item_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        with get_db_session() as session:
            shop_repository = ShopRepository(session)
            shop_items = shop_repository.list_all(only_enabled=True)

        current_lower = current.lower()
        choices: list[app_commands.Choice[str]] = []

        for shop_item in shop_items:
            item = shop_item.item_definition
            if (
                current_lower in item.code.lower()
                or current_lower in item.name.lower()
            ):
                choices.append(
                    app_commands.Choice(
                        name=f"{item.name} ({item.code})",
                        value=item.code,
                    )
                )

            if len(choices) >= 25:
                break

        return choices


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ShopCog(bot))
