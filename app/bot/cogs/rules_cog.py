"""Règlement du serveur : `/reglement` et le panneau du salon du règlement.

Le panneau (bandeau, règlement, bouton « J'accepte ») est posté au démarrage
s'il n'y est pas, et réécrit si `rules.json` a changé. Le bouton est
persistant : il marche après un redémarrage. Le contrôle lui-même est dans
`app/bot/rules_gate.py`.
"""

from __future__ import annotations

import asyncio
import io
import logging

import discord
from discord import app_commands
from discord.ext import commands

from app.bot import rules_gate
from app.bot.embeds.rules_embeds import BANNER, build_rules_embed
from app.bot.rendering.welcome_card import compose_rules_card
from app.domain.services.rules_service import needs_acceptance, validate
from app.infrastructure.config.settings import settings
from app.infrastructure.rules.rules_loader import get_rules

_logger = logging.getLogger(__name__)


def is_panel(message: discord.Message, bot_id: int) -> bool:
    """Le panneau du bot : reconnu à son bouton, pas à son texte (qui change)."""
    if message.author.id != bot_id:
        return False
    return any(getattr(child, "custom_id", None) == rules_gate.ACCEPT_ID
               for row in message.components for child in getattr(row, "children", ()))


def _content(embed: discord.Embed) -> tuple:
    return (embed.title, embed.description, embed.footer.text,
            tuple((f.name, f.value) for f in embed.fields))


def same_panel(message: discord.Message, embed: discord.Embed) -> bool:
    return bool(message.embeds) and _content(message.embeds[0]) == _content(embed)


class RulesCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.bot.add_view(rules_gate.RulesAcceptView())
        self._panel_task = asyncio.ensure_future(self._ensure_panel())

    def cog_unload(self) -> None:
        self._panel_task.cancel()

    async def _ensure_panel(self) -> None:
        await self.bot.wait_until_ready()
        channel = self.bot.get_channel(settings.rules_channel_id) if settings.rules_channel_id else None
        if channel is None:
            _logger.warning("salon du règlement introuvable (%s)", settings.rules_channel_id)
            return
        rules = get_rules()
        problems = validate(rules)
        if problems:
            _logger.error("rules.json refusé, panneau inchangé : %s", " / ".join(problems))
            return
        await post_or_update_panel(channel, self.bot.user.id, rules)

    @app_commands.command(name="reglement", description="Le règlement du serveur, à accepter pour jouer")
    async def reglement(self, interaction: discord.Interaction) -> None:
        rules = get_rules()
        found = await rules_gate.read_acceptance(interaction.user.id)
        kwargs = {"embed": build_rules_embed(rules), "ephemeral": True}
        if found is not None and not needs_acceptance(found.version, rules):
            kwargs["content"] = f"✅ Tu as accepté ce règlement le {rules_gate.timestamp(found.accepted_at)}."
        else:
            kwargs["content"] = rules_gate.ASK_AGAIN if found is not None else rules_gate.ASK_FIRST
            kwargs["view"] = rules_gate.RulesAcceptView()
        await interaction.response.send_message(**kwargs)


async def post_or_update_panel(channel, bot_id: int, rules) -> str:
    """Poste le panneau, ou le réécrit si le règlement a changé. Renvoie ce
    qui a été fait : "posté", "mis à jour" ou "inchangé"."""
    embed = build_rules_embed(rules, banner=True)
    try:
        panel = None
        async for message in channel.history(limit=50):
            if is_panel(message, bot_id):
                panel = message
                break
        if panel is not None and same_panel(panel, embed):
            return "inchangé"
        card = await asyncio.to_thread(compose_rules_card)
        file = discord.File(io.BytesIO(card), filename=BANNER)
        if panel is None:
            await channel.send(embed=embed, file=file, view=rules_gate.RulesAcceptView())
            return "posté"
        await panel.edit(embed=embed, attachments=[file], view=rules_gate.RulesAcceptView())
        return "mis à jour"
    except discord.HTTPException:
        _logger.warning("panneau du règlement impossible dans %s", getattr(channel, "id", "?"), exc_info=True)
        return "échec"


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(RulesCog(bot))
