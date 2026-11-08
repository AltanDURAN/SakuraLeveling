"""Parcours d'arrivée : filet de sécurité des rôles (08/11/2026).

Au démarrage puis toutes les 30 minutes, chaque membre reçoit les rôles de son
parcours qui lui manquent (Rang F s'il a accepté le règlement, Aventurier s'il
a aussi fini ou passé le tutoriel) : un rôle raté pendant une panne de Discord,
un membre revenu pendant que le bot était éteint. Rien n'est jamais retiré.
Les permissions des salons, elles, ne changent qu'avec `/admin acces`.
"""

from __future__ import annotations

import logging

from discord.ext import commands, tasks

from app.bot import access
from app.infrastructure.config.settings import settings

_logger = logging.getLogger(__name__)


class AccessCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.reconcile_loop.start()

    def cog_unload(self) -> None:
        self.reconcile_loop.cancel()

    @tasks.loop(minutes=30)
    async def reconcile_loop(self) -> None:
        guild = self.bot.get_guild(settings.discord_guild_id) if settings.discord_guild_id else None
        if guild is None:
            return
        try:
            ranks, adventurers = await access.reconcile(guild)
        except Exception:  # noqa: BLE001 — la boucle doit survivre
            _logger.exception("parcours : rattrapage des rôles impossible")
            return
        if ranks or adventurers:
            _logger.info("parcours : %d rang(s) et %d rôle(s) Aventurier rendus", ranks, adventurers)

    @reconcile_loop.before_loop
    async def _wait_ready(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AccessCog(bot))
