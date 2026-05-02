import logging

import discord
from discord import app_commands
from discord.ext import commands, tasks

from app.application.use_cases.create_trade import (
    CreateTradeUseCase,
    TradeOffer,
)
from app.bot.embeds.trade_embeds import build_trade_embed
from app.bot.views.trade_view import TradeProposalModal, TradeResponseView
from app.infrastructure.config.settings import settings
from app.infrastructure.db.repositories.inventory_repository import InventoryRepository
from app.infrastructure.db.repositories.item_repository import ItemRepository
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.repositories.trade_repository import TradeRepository
from app.infrastructure.db.session import get_db_session


TRADE_TTL_MINUTES = 5

_logger = logging.getLogger(__name__)


class TradeCog(commands.Cog):
    """Échange entre joueurs : items et/ou or, dans les deux sens."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.expire_loop.start()

    def cog_unload(self) -> None:
        self.expire_loop.cancel()

    @tasks.loop(minutes=1)
    async def expire_loop(self) -> None:
        """Marque les trades pending dépassés en status=expired toutes les
        minutes. Évite que des trades restent éternellement en pending et
        bloquent les nouvelles propositions entre les mêmes joueurs."""
        try:
            with get_db_session() as session:
                expired_count = TradeRepository(session).expire_overdue_pending()
            if expired_count > 0:
                _logger.info("Trade cleanup: %d trade(s) marqués expired", expired_count)
        except Exception:
            # Ne plante jamais le bot pour un pb de cleanup ; juste log.
            _logger.exception("Trade cleanup loop failed")

    @expire_loop.before_loop
    async def _before_expire_loop(self) -> None:
        await self.bot.wait_until_ready()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.channel_id != settings.beta_channel_id:
            message = (
                "🚧 Le bot est actuellement en phase de test.\n"
                "Utilisez le channel beta dédié."
            )
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
            return False
        return True

    @app_commands.command(
        name="trade",
        description="Proposer un échange à un autre joueur (items et/ou or)",
    )
    @app_commands.describe(target="Joueur avec qui échanger")
    async def trade(
        self,
        interaction: discord.Interaction,
        target: discord.Member,
    ) -> None:
        if target.bot:
            await interaction.response.send_message(
                "❌ Vous ne pouvez pas échanger avec un bot.",
                ephemeral=True,
            )
            return

        if target.id == interaction.user.id:
            await interaction.response.send_message(
                "❌ Vous ne pouvez pas échanger avec vous-même.",
                ephemeral=True,
            )
            return

        async def on_modal_submit(
            interaction: discord.Interaction,
            offered_items: list[tuple[str, int]],
            offered_gold: int,
            requested_items: list[tuple[str, int]],
            requested_gold: int,
        ) -> None:
            # `target` est capturé par closure ici
            await self._create_trade_with_target(
                interaction=interaction,
                target=target,
                offered_items=offered_items,
                offered_gold=offered_gold,
                requested_items=requested_items,
                requested_gold=requested_gold,
            )

        modal = TradeProposalModal(
            target_member=target,
            target_display_name=target.display_name,
            on_submit_callback=on_modal_submit,
        )
        await interaction.response.send_modal(modal)

    async def _create_trade_with_target(
        self,
        interaction: discord.Interaction,
        target: discord.Member,
        offered_items: list[tuple[str, int]],
        offered_gold: int,
        requested_items: list[tuple[str, int]],
        requested_gold: int,
    ) -> None:
        with get_db_session() as session:
            use_case = CreateTradeUseCase(
                player_repository=PlayerRepository(session),
                inventory_repository=InventoryRepository(session),
                item_repository=ItemRepository(session),
                trade_repository=TradeRepository(session),
            )
            result = use_case.execute(
                initiator_discord_id=interaction.user.id,
                target_discord_id=target.id,
                initiator_username=interaction.user.name,
                initiator_display_name=interaction.user.display_name,
                target_display_name=target.display_name,
                initiator_offer=TradeOffer(items=offered_items, gold=offered_gold),
                target_request=TradeOffer(items=requested_items, gold=requested_gold),
                ttl_minutes=TRADE_TTL_MINUTES,
            )

        if not result.success or result.trade is None:
            await interaction.response.send_message(result.message, ephemeral=True)
            return

        embed = build_trade_embed(result.trade)
        view = TradeResponseView(
            trade_id=result.trade.id,
            initiator_discord_id=result.trade.initiator_discord_id,
            target_discord_id=result.trade.target_discord_id,
            timeout=TRADE_TTL_MINUTES * 60,
        )

        await interaction.response.send_message(
            content=f"{target.mention}, {interaction.user.mention} vous propose un échange :",
            embed=embed,
            view=view,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TradeCog(bot))
