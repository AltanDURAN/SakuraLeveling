"""Cog des artisans : `/forgeron` et `/alchimiste`.

Chaque commande fait APPARAÎTRE le personnage. Borak FUSIONNE deux copies
identiques en une plus rare — toutes les pièces, accessoires compris depuis le
26/10/2026 (cf. `FusionView` / `FuseGearUseCase`). Elna, l'alchimiste, prépare
les POTIONS (cf. `AlchemyView` / `BrewPotionUseCase`). Leur maîtrise monte à
chaque fusion / potion.
"""

from __future__ import annotations

import asyncio

import discord
from discord import app_commands
from discord.ext import commands

from app.bot.cogs._mixins import BetaChannelOnlyMixin
from app.bot.views.alchemy_view import AlchemyView
from app.bot.views.fusion_view import FusionView
from app.domain.services.artisan_service import ArtisanService
from app.infrastructure.artisans import artisan_loader
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.session import get_db_session


class ArtisanCog(BetaChannelOnlyMixin, commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def _open(
        self, interaction: discord.Interaction, artisan_code: str,
    ) -> None:
        definition = artisan_loader.get_artisan(artisan_code)
        if definition is None:
            await interaction.response.send_message(
                f"❌ Aucun artisan « {artisan_code} » n'est configuré.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)
        with get_db_session() as session:
            profile = PlayerRepository(session).get_or_create_by_discord_id(
                discord_id=interaction.user.id,
                username=interaction.user.name,
                display_name=interaction.user.display_name,
            )
            player_id = profile.player.id

        view = FusionView(
            definition=definition,
            player_id=player_id,
            session_factory=get_db_session,
            artisan_service=ArtisanService(artisan_loader.load_pricing()),
        )
        await asyncio.to_thread(view.refresh_data)
        view.build()
        embed, file = await view.render()
        await interaction.followup.send(
            embed=embed, file=file, view=view, ephemeral=True,
        )

    @app_commands.command(
        name="forgeron",
        description="Va voir le forgeron : il fusionne toutes tes pièces, accessoires compris",
    )
    async def forgeron(self, interaction: discord.Interaction) -> None:
        await self._open(interaction, "forgeron")

    @app_commands.command(
        name="alchimiste",
        description="Va voir l'alchimiste : elle prépare tes potions avec les matériaux des monstres",
    )
    async def alchimiste(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        with get_db_session() as session:
            profile = PlayerRepository(session).get_or_create_by_discord_id(
                discord_id=interaction.user.id,
                username=interaction.user.name,
                display_name=interaction.user.display_name,
            )
            player_id = profile.player.id
        view = AlchemyView(player_id, get_db_session)
        await asyncio.to_thread(view.refresh_data)
        view.build()
        embed, file = await view.render()
        await interaction.followup.send(embed=embed, file=file, view=view, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ArtisanCog(bot))
