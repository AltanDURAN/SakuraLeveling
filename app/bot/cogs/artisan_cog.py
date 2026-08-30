"""Cog des artisans : `/forgeron` et `/artisan`.

Chaque commande fait APPARAÎTRE le personnage. Le joueur choisit ensuite dans
des menus ; il ne tape jamais de code d'objet.

Une boucle d'une minute passe les travaux échus en « prêt » et prévient leur
propriétaire dans le salon où la commande a été lancée. Elle est idempotente :
un redémarrage du bot ne perd ni ne double une notification.
"""

from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands, tasks

from app.application.use_cases.artisan_work import ArtisanWorkUseCase
from app.bot.cogs._mixins import BetaChannelOnlyMixin
from app.bot.views.artisan_view import ArtisanView
from app.domain.services.artisan_service import ArtisanService
from app.infrastructure.artisans import artisan_loader
from app.infrastructure.db.repositories.craft_repository import CraftRepository
from app.infrastructure.db.repositories.inventory_repository import (
    InventoryRepository,
)
from app.infrastructure.db.repositories.item_repository import ItemRepository
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.repositories.work_order_repository import (
    WorkOrderRepository,
)
from app.infrastructure.db.session import get_db_session

_logger = logging.getLogger("sakura.artisans")


def _use_case_factory(session) -> ArtisanWorkUseCase:
    return ArtisanWorkUseCase(
        player_repository=PlayerRepository(session),
        inventory_repository=InventoryRepository(session),
        item_repository=ItemRepository(session),
        craft_repository=CraftRepository(session),
        work_order_repository=WorkOrderRepository(session),
        artisan_service=ArtisanService(artisan_loader.load_pricing()),
    )


class ArtisanCog(BetaChannelOnlyMixin, commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.ready_loop.start()

    def cog_unload(self) -> None:
        self.ready_loop.cancel()

    # ------------------------------------------------------------ commun --
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

        view = ArtisanView(
            definition=definition,
            player_id=player_id,
            session_factory=get_db_session,
            use_case_factory=_use_case_factory,
            artisan_service=ArtisanService(artisan_loader.load_pricing()),
            channel_id=interaction.channel_id or 0,
        )
        import asyncio

        await asyncio.to_thread(view.refresh_data)
        view._build_components()
        embed, file = await view.render()
        await interaction.followup.send(
            embed=embed, file=file, view=view, ephemeral=True,
        )

    # --------------------------------------------------------- commandes --
    @app_commands.command(
        name="forgeron",
        description="Va voir le forgeron : armes, boucliers, pièces de tête et de corps",
    )
    async def forgeron(self, interaction: discord.Interaction) -> None:
        await self._open(interaction, "forgeron")

    @app_commands.command(
        name="artisan",
        description="Va voir l'artisane : elle confectionne les accessoires",
    )
    async def artisan(self, interaction: discord.Interaction) -> None:
        await self._open(interaction, "artisan")

    # ------------------------------------------------------------ boucle --
    @tasks.loop(minutes=1)
    async def ready_loop(self) -> None:
        """Passe les travaux échus en « prêt » et prévient leur propriétaire."""
        try:
            with get_db_session() as session:
                repo = WorkOrderRepository(session)
                due = repo.mark_ready_due()
                to_notify = []
                for order in due:
                    profile = PlayerRepository(session).get_profile_by_player_id(
                        order.player_id,
                    )
                    item = ItemRepository(session).get_by_id(
                        order.result_item_definition_id,
                    )
                    definition = artisan_loader.get_artisan(order.artisan_code)
                    to_notify.append(
                        (
                            order.id,
                            order.notify_channel_id,
                            profile.player.discord_id if profile else 0,
                            item.name if item else order.recipe_code,
                            definition.name if definition else order.artisan_code,
                            definition.work_noun if definition else "travail",
                        )
                    )
                    repo.mark_notified(order.id)
                session.commit()
        except Exception:  # noqa: BLE001
            _logger.exception("Boucle des artisans : échec de la relève")
            return

        for _oid, channel_id, discord_id, item_name, npc, noun in to_notify:
            if not channel_id or not discord_id:
                continue
            channel = self.bot.get_channel(channel_id)
            if channel is None:
                continue
            try:
                await channel.send(
                    f"⚒️ <@{discord_id}> — **{npc}** a terminé sa {noun} : "
                    f"**{item_name}** t'attend. Passe le récupérer."
                )
            except discord.HTTPException:
                _logger.warning(
                    "Notification d'artisan impossible dans le salon %s", channel_id,
                )

    @ready_loop.before_loop
    async def _before_ready_loop(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ArtisanCog(bot))
