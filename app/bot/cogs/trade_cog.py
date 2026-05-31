import logging

import discord
from discord import app_commands
from discord.ext import commands, tasks

from app.bot.views.trade_draft_view import TradeDraftView
from app.infrastructure.config.settings import settings
from app.infrastructure.db.repositories.trade_repository import TradeRepository
from app.infrastructure.db.session import get_db_session
from app.bot.cogs._mixins import BetaChannelOnlyMixin


TRADE_TTL_MINUTES = 5

_logger = logging.getLogger(__name__)


class TradeCog(BetaChannelOnlyMixin, commands.Cog):
    """Échange entre joueurs : items et/ou or, dans les deux sens."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.expire_loop.start()

    def cog_unload(self) -> None:
        self.expire_loop.cancel()

    @tasks.loop(minutes=5)
    async def expire_loop(self) -> None:
        """Marque les trades pending dépassés en status=expired toutes les
        5 minutes. Évite que des trades restent éternellement en pending et
        bloquent les nouvelles propositions entre les mêmes joueurs (TTL 5 min,
        donc un trade peut rester pending 5-10 min avant cleanup ; négligeable)."""
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

        view = TradeDraftView(
            initiator=interaction.user,
            target=target,
            timeout=TRADE_TTL_MINUTES * 60,
        )
        await interaction.response.send_message(
            embed=view._build_embed(),
            view=view,
            ephemeral=True,
        )
        view.draft_message = await interaction.original_response()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TradeCog(bot))
