"""Guides épinglés des salons du world boss et de la tour solo (07/11/2026).

Le premier message de chaque salon, épinglé : ce qu'on y fait, les règles,
les commandes. Posté s'il n'y est pas, réécrit quand son texte change (un
horaire du raid réglé depuis le site : vérifié toutes les 30 minutes, sans
redémarrage). Reconnu à son pied de page, parmi les épinglés ou en tête du
salon ; la notice « a épinglé un message » est retirée.
"""

from __future__ import annotations

import asyncio
import io
import logging
from collections.abc import Callable
from dataclasses import dataclass

import discord
from discord.ext import commands, tasks

from app.bot.cogs.rules_cog import same_panel
from app.bot.embeds import channel_guide_embeds as guides
from app.bot.rendering.welcome_card import compose_channel_card
from app.infrastructure.config.settings import settings
from app.infrastructure.pacing.pacing_loader import get_pacing
from app.infrastructure.world_boss.boss_definition_loader import list_definitions

_logger = logging.getLogger(__name__)

#: Messages relus en tête du salon si le guide n'est plus épinglé.
HEAD_SCAN_LIMIT = 20


@dataclass(frozen=True)
class Guide:
    channel_id: int
    embed: discord.Embed
    banner: tuple[str, str, str, int]
    filename: str


def current_guides() -> list[Guide]:
    """Les guides à tenir, avec le texte d'aujourd'hui (réglages compris)."""
    from app.bot.cogs.world_boss_cog import ACTIVE_DAYS

    found = []
    if settings.boss_channel_id:
        level = guides.first_raid_level([d.level for d in list_definitions() if getattr(d, "level", 0)])
        found.append(Guide(settings.boss_channel_id,
                           guides.build_world_boss_guide(get_pacing().raid, level, ACTIVE_DAYS),
                           guides.WORLD_BOSS_BANNER, guides.WORLD_BOSS_FILE))
    if settings.tower_channel_id:
        found.append(Guide(settings.tower_channel_id, guides.build_tower_guide(),
                           guides.TOWER_BANNER, guides.TOWER_FILE))
    return found


def is_guide(message: discord.Message, bot_id: int) -> bool:
    return (message.author.id == bot_id and bool(message.embeds)
            and (message.embeds[0].footer.text or "") == guides.GUIDE_FOOTER)


async def find_guide(channel, bot_id: int):
    async for message in channel.pins(limit=50):
        if is_guide(message, bot_id):
            return message
    async for message in channel.history(limit=HEAD_SCAN_LIMIT, oldest_first=True):
        if is_guide(message, bot_id):
            return message
    return None


async def pin_message(channel, message, bot_id: int) -> None:
    """Épingle, puis retire la notice « … a épinglé un message » du bot."""
    try:
        await message.pin(reason="Message du salon")
    except discord.HTTPException:
        _logger.warning("guide non épinglé dans %s (droit « Épingler des messages » ?)",
                        getattr(channel, "id", "?"), exc_info=True)
        return
    try:
        async for notice in channel.history(limit=5):
            if notice.type == discord.MessageType.pins_add and notice.author.id == bot_id:
                await notice.delete()
                break
    except discord.HTTPException:
        _logger.info("notice d'épinglage laissée dans %s", getattr(channel, "id", "?"))


async def post_or_update_guide(channel, bot_id: int, guide: Guide,
                               banner: Callable[..., bytes] = compose_channel_card) -> str:
    """Poste le guide (épinglé), ou le réécrit si son texte a changé. Renvoie
    "posté", "mis à jour", "inchangé" ou "échec"."""
    try:
        message = await find_guide(channel, bot_id)
        if message is not None and same_panel(message, guide.embed):
            if not message.pinned:
                await pin_message(channel, message, bot_id)
            return "inchangé"
        image = await asyncio.to_thread(banner, *guide.banner)
        file = discord.File(io.BytesIO(image), filename=guide.filename)
        if message is None:
            message = await channel.send(embed=guide.embed, file=file)
            await pin_message(channel, message, bot_id)
            return "posté"
        await message.edit(embed=guide.embed, attachments=[file])
        if not message.pinned:
            await pin_message(channel, message, bot_id)
        return "mis à jour"
    except discord.HTTPException:
        _logger.warning("guide impossible dans %s", getattr(channel, "id", "?"), exc_info=True)
        return "échec"


class ChannelGuidesCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.refresh_loop.start()

    def cog_unload(self) -> None:
        self.refresh_loop.cancel()

    @tasks.loop(minutes=30)
    async def refresh_loop(self) -> None:
        for guide in current_guides():
            channel = self.bot.get_channel(guide.channel_id)
            if channel is None:
                _logger.warning("salon du guide introuvable (%s)", guide.channel_id)
                continue
            outcome = await post_or_update_guide(channel, self.bot.user.id, guide)
            if outcome != "inchangé":
                _logger.info("guide du salon %s : %s", guide.channel_id, outcome)

    @refresh_loop.before_loop
    async def _wait_ready(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ChannelGuidesCog(bot))
