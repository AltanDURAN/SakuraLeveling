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



def _records_screen(view, player_id: int, seed: int):
    """`/records` en image (DA du bot, 21/11/2026) : chaque record, son
    détenteur, et où en est le joueur."""
    from app.bot.embeds.records_embeds import value_text
    from app.bot.embeds.screen_embed import image_embed
    from app.bot.rendering import screens
    from app.domain.services import records_service as rs
    from app.shared.formatters import format_int

    def name(pid):
        return view.names.get(pid, (0, "?"))[1]

    def row(record):
        entry, mine = view.held.get(record.code), view.mine.get(record.code)
        mine_value = mine.value if mine else 0
        value = screens.plain(value_text(record, entry.value)) if entry else "—"
        if entry is not None and entry.player_id == player_id:
            return screens.Row(record.emoji, record.label, value, "👑 c'est toi", tone="gold")
        if entry is None:
            sub = (f"toi {screens.plain(value_text(record, mine_value))} : à toi cette nuit"
                   if mine_value and not view.excluded else "personne : à prendre")
            return screens.Row(record.emoji, record.label, value, sub)
        if mine_value > entry.value:
            sub = f"{name(entry.player_id)} · 🔥 toi {screens.plain(value_text(record, mine_value))} : mieux que le record !"
        elif mine_value:
            sub = (f"{name(entry.player_id)} · toi {screens.plain(value_text(record, mine_value))}, "
                   f"il te manque {format_int(entry.value - mine_value + 1)}")
        else:
            sub = f"{name(entry.player_id)} · toi : —"
        return screens.Row(record.emoji, record.label, value, sub,
                           ratio=min(1.0, mine_value / entry.value) if entry.value else None)

    colors = {"exploits": (255, 120, 80), "defis": (120, 200, 160), "tour": (150, 140, 230),
              "boss": (240, 196, 92), "chasse": (200, 140, 90), "collection": (230, 120, 200)}
    sections = [screens.Section(heading, [row(r) for r in view.records if r.category == category],
                                colors.get(category, (150, 120, 210)))
                for category, heading in rs.CATEGORIES]
    sections = [s for s in sections if s.rows]
    held = sum(1 for e in view.held.values() if e.player_id == player_id)
    return image_embed(screens.compose_list, f"records_{seed}", discord.Color.gold(),
                       title="🏆 Tes records", subtitle="Mis à jour chaque nuit à minuit : bats un record aujourd'hui, il est à toi cette nuit",
                       sections=sections, chips=[f"👑 {held} record{'s' if held > 1 else ''} sur {len(view.records)}"],
                       footer="🥇 Le plus de records détenus = un titre et +5 % d'or en zone, redistribué chaque nuit.",
                       seed=seed)

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
        screen = await asyncio.to_thread(_records_screen, view, player_id, interaction.user.id)
        if screen is not None:
            await interaction.followup.send(embed=screen[0], file=screen[1], ephemeral=True)
            return
        await interaction.followup.send(embed=build_personal_embed(view, player_id), ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(RecordsCog(bot))
