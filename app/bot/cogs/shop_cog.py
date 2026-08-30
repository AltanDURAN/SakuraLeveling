"""Cog du marchand : `/marchand`.

Remplace l'ancien duo `/boutique` + `/acheter` : on va voir le personnage, on
choisit un rayon puis un article dans des menus, et on achète au bouton. Plus
aucun code d'objet à taper.

L'achat lui-même passe toujours par `BuyFromShopUseCase` — seule la façade a
changé. La vente joueur→marchand n'existe pas (décision V2).
"""

import asyncio

import discord
from discord import app_commands
from discord.ext import commands

from app.application.use_cases.buy_from_shop import BuyFromShopUseCase
from app.bot.cogs._mixins import BetaChannelOnlyMixin
from app.bot.views.merchant_view import MerchantView
from app.domain.services.shop_pricing_service import ShopPricingService
from app.infrastructure.artisans import artisan_loader
from app.infrastructure.db.repositories.inventory_repository import (
    InventoryRepository,
)
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.repositories.shop_repository import ShopRepository
from app.infrastructure.db.session import get_db_session


def _buy_use_case(session) -> BuyFromShopUseCase:
    return BuyFromShopUseCase(
        player_repository=PlayerRepository(session),
        inventory_repository=InventoryRepository(session),
        shop_repository=ShopRepository(session),
        shop_pricing_service=ShopPricingService(),
    )


class ShopCog(BetaChannelOnlyMixin, commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="marchand",
        description="Va voir le marchand et achète ses articles",
    )
    async def marchand(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)

        with get_db_session() as session:
            profile = PlayerRepository(session).get_or_create_by_discord_id(
                discord_id=interaction.user.id,
                username=interaction.user.name,
                display_name=interaction.user.display_name,
            )
            player_id = profile.player.id

        view = MerchantView(
            definition=artisan_loader.get_merchant(),
            player_id=player_id,
            session_factory=get_db_session,
            buy_use_case_factory=_buy_use_case,
            discord_user=interaction.user,
        )
        await asyncio.to_thread(view.refresh_data)
        view._build_components()
        embed, file = await view.render()
        await interaction.followup.send(
            embed=embed, file=file, view=view, ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ShopCog(bot))
