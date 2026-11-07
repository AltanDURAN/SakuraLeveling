"""Salon des records (07/11/2026, idée de l'auteur) et `/records`.

Chaque nuit à minuit (heure de Paris) : le tableau épinglé du salon est
réécrit (détenteur et score de chaque record, titres tournants), puis un
message dit ce qui a changé en mentionnant les nouveaux détenteurs. Vérifié
toutes les 5 minutes, une seule fois par jour (`record_board.last_day`) : un
redémarrage ne rejoue rien, un bot éteint à minuit rattrape à son retour.
"""

from __future__ import annotations

import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import commands, tasks

from app.application.use_cases import records
from app.bot.cogs.channel_guides_cog import pin_message
from app.bot.embeds.records_embeds import build_board_embed, build_news, build_personal_embed
from app.infrastructure.config.settings import settings
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.session import get_db_session

_logger = logging.getLogger(__name__)


class RecordsCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.night_loop.start()

    def cog_unload(self) -> None:
        self.night_loop.cancel()

    @staticmethod
    def _run_night():
        with get_db_session() as session:
            return records.run_night(session)

    @staticmethod
    def _save_message(message_id: int) -> None:
        with get_db_session() as session:
            records.set_board_message(session, message_id)

    @tasks.loop(minutes=5)
    async def night_loop(self) -> None:
        if not settings.records_channel_id:
            return
        try:
            report = await asyncio.to_thread(self._run_night)
            if report is not None:
                await self.publish(report)
        except Exception:
            _logger.exception("mise à jour des records échouée")

    @night_loop.before_loop
    async def _wait_ready(self) -> None:
        await self.bot.wait_until_ready()

    async def publish(self, report) -> None:
        channel = self.bot.get_channel(settings.records_channel_id)
        if channel is None:
            _logger.warning("salon des records introuvable (%s)", settings.records_channel_id)
            return
        board = build_board_embed(report.records, report.held, report.standings, report.names, report.day)
        message = None
        if report.message_id:
            try:
                message = await channel.fetch_message(report.message_id)
            except discord.NotFound:
                message = None
        if message is None:
            message = await channel.send(embed=board)
            await pin_message(channel, message, self.bot.user.id)
            await asyncio.to_thread(self._save_message, message.id)
        else:
            await message.edit(embed=board)
            if not message.pinned:
                await pin_message(channel, message, self.bot.user.id)

        news, ping = build_news(report.changes, report.new_titles, report.standings, report.names, report.first)
        if news is None:
            return
        users = [report.names[p][0] for p in ping if p in report.names and report.names[p][0]]
        await channel.send(
            content=" ".join(f"<@{u}>" for u in users) or None, embed=news,
            allowed_mentions=discord.AllowedMentions(users=[discord.Object(u) for u in users],
                                                     roles=False, everyone=False))
        _logger.info("records de la nuit du %s publiés (%d changements)", report.day, len(report.changes))

    @staticmethod
    def _personal(discord_id: int):
        with get_db_session() as session:
            profile = PlayerRepository(session).get_by_discord_id(discord_id)
            if profile is None:
                return None, None
            return profile.player.id, records.personal(session, profile.player.id)

    @app_commands.command(name="records", description="Les records du serveur, et où tu en es")
    async def records_command(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        player_id, view = await asyncio.to_thread(self._personal, interaction.user.id)
        if view is None:
            await interaction.followup.send("Tu n'as pas encore de personnage : commence par `/demarrer`.",
                                            ephemeral=True)
            return
        await interaction.followup.send(embed=build_personal_embed(view, player_id), ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(RecordsCog(bot))
