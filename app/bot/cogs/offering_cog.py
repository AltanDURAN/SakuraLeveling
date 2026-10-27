"""Cog `/offrande` : l'offrande commune (27/10/2026, idée de l'auteur).

Tout le serveur verse de l'or dans une jauge ; pleine, elle invoque une
divinité au hasard qui bénit tout le monde pendant 24 h. Une fois par jour,
de plus en plus chère. Règles : `offering_service` ; jauge : `use_cases/offering`.
"""

from __future__ import annotations

import asyncio
import logging
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands

from app.application.use_cases import offering
from app.bot.cogs._mixins import BetaChannelOnlyMixin
from app.domain.services import offering_service as osvc
from app.infrastructure.config.settings import settings
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.session import get_db_session
from app.infrastructure.offering import deity_loader
from app.shared.formatters import format_int

_logger = logging.getLogger("sakura.offering")
_PARIS = ZoneInfo("Europe/Paris")
_AMOUNTS = (1_000, 10_000, 100_000)


def _bar(value: int, target: int, width: int = 16) -> str:
    filled = round(width * min(1.0, value / max(1, target)))
    return "▰" * filled + "▱" * (width - filled)


def build_offering_embed(state: offering.OfferingStatus) -> discord.Embed:
    embed = discord.Embed(
        title="🙏 L'Offrande",
        description=("Tout le serveur verse de l'or dans la jauge. Pleine, elle **invoque une "
                     "divinité** qui bénit TOUT le monde pendant 24 h. Une fois par jour ; chaque "
                     "remplissage rend la suivante plus chère, chaque jour sans la fait redescendre."),
        color=discord.Color.from_rgb(214, 170, 74),
    )
    if state.open:
        pct = round(100 * state.contributed / max(1, state.target))
        gauge = (f"{_bar(state.contributed, state.target)}\n**{format_int(state.contributed)} / "
                 f"{format_int(state.target)}** or ({pct} %)")
    else:
        gauge = f"✅ Exaucée aujourd'hui — elle rouvre à minuit (prochaine : {format_int(state.target)} or)."
    embed.add_field(name=f"Jauge n° {state.fills + 1}", value=gauge, inline=False)
    if state.blessing is not None and state.blessing_until is not None:
        until = state.blessing_until.astimezone(_PARIS).strftime("%d/%m à %H h %M")
        embed.add_field(name="✨ Bénédiction en cours",
                        value=f"{state.blessing.label}\n{state.blessing.blessing} — jusqu'au {until}",
                        inline=False)
    if state.top:
        embed.add_field(name="Donateurs de cette jauge",
                        value="\n".join(f"• {name} — {format_int(amount)} or" for name, amount in state.top),
                        inline=False)
    embed.add_field(name="Les divinités",
                    value="\n".join(f"{d.emoji} **{d.name}** — {d.blessing}" for d in deity_loader.list_deities()),
                    inline=False)
    embed.set_footer(text=f"Ton don dans cette jauge : {format_int(state.mine)} or")
    return embed


def build_invocation_embed(deity: osvc.Deity, donor: str) -> discord.Embed:
    return discord.Embed(
        title=f"{deity.emoji} {deity.name} répond à l'offrande !",
        description=(f"La jauge est pleine — merci à tous, et à **{donor}** qui l'a complétée.\n"
                     f"**{deity.name}, {deity.title}**, bénit tout le serveur pendant 24 h :\n"
                     f"> {deity.blessing}"),
        color=discord.Color.from_rgb(214, 170, 74),
    )


def _profile(session, user):
    return PlayerRepository(session).get_or_create_by_discord_id(
        discord_id=user.id, username=user.name, display_name=user.display_name,
    )


def _status(user):
    with get_db_session() as session:
        return offering.status(session, _profile(session, user))


def _give(user, amount: int):
    with get_db_session() as session:
        try:
            return offering.contribute(session, _profile(session, user), amount), None
        except offering.OfferingError as e:
            return None, str(e)


class AmountModal(discord.ui.Modal, title="Faire une offrande"):
    amount = discord.ui.TextInput(label="Montant (or)", placeholder="ex. 25000", max_length=12)

    def __init__(self, offering_view: "OfferingView") -> None:
        super().__init__()
        self.offering_view = offering_view

    async def on_submit(self, interaction: discord.Interaction) -> None:
        raw = str(self.amount.value).replace(" ", "").replace(" ", "")
        if not raw.isdigit():
            await interaction.response.send_message("Un nombre entier, s'il te plaît.", ephemeral=True)
            return
        await self.offering_view.give(interaction, int(raw))


class OfferingView(discord.ui.View):
    def __init__(self, cog: "OfferingCog", state: offering.OfferingStatus) -> None:
        super().__init__(timeout=600)
        self.cog = cog
        for amount in _AMOUNTS:
            button = discord.ui.Button(label=f"Offrir {format_int(amount)}", emoji="💰",
                                       style=discord.ButtonStyle.primary, disabled=not state.open)
            button.callback = self._giver(amount)
            self.add_item(button)
        other = discord.ui.Button(label="Autre montant…", style=discord.ButtonStyle.secondary,
                                  disabled=not state.open)
        other.callback = self._ask
        self.add_item(other)

    def _giver(self, amount: int):
        async def callback(interaction: discord.Interaction) -> None:
            await self.give(interaction, amount)
        return callback

    async def _ask(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(AmountModal(self))

    async def give(self, interaction: discord.Interaction, amount: int) -> None:
        await interaction.response.defer(ephemeral=True)
        outcome, error = await asyncio.to_thread(_give, interaction.user, amount)
        if error:
            await interaction.followup.send(error, ephemeral=True)
            return
        await interaction.followup.send(f"🙏 Tu offres **{format_int(outcome.given)}** or.", ephemeral=True)
        if outcome.invoked is not None:
            await self.cog.announce(interaction, outcome.invoked)
        try:
            for item in self.children:
                item.disabled = not outcome.status.open
            await interaction.message.edit(embed=build_offering_embed(outcome.status), view=self)
        except discord.HTTPException:
            _logger.warning("rafraîchissement de /offrande échoué", exc_info=True)


class OfferingCog(BetaChannelOnlyMixin, commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="offrande", description="L'offrande commune : remplis la jauge, invoque une divinité")
    async def offrande(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        state = await asyncio.to_thread(_status, interaction.user)
        await interaction.followup.send(embed=build_offering_embed(state), view=OfferingView(self, state))

    async def announce(self, interaction: discord.Interaction, deity: osvc.Deity) -> None:
        """La divinité invoquée : dans le salon de la commande et le salon général."""
        embed = build_invocation_embed(deity, interaction.user.display_name)
        targets = {interaction.channel_id}
        if settings.rank_announce_channel_id:
            targets.add(settings.rank_announce_channel_id)
        for channel_id in targets:
            channel = self.bot.get_channel(channel_id)
            if channel is None:
                continue
            try:
                await channel.send(embed=embed)
            except discord.HTTPException:
                _logger.warning("annonce de l'offrande dans %s échouée", channel_id, exc_info=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(OfferingCog(bot))
