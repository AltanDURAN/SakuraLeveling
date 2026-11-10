"""Événements saisonniers (décembre 2026, demande de l'auteur) : calendrier de
l'Avent, cadeau de Noël, sucres d'orge, atelier des lutins, Nouvel An.

  • salon des événements (`settings.event_channel_id` — gardé aux GROS
    événements) : un PANNEAU épinglé (ce qui se passe, ce qui vient, boutons
    persistants) et les ANNONCES, chacune une seule fois (gardées en base) :
    ouverture de l'Avent, début des sucres d'orge, matin de Noël, ouverture
    d'une boutique, minuit du Nouvel An (@everyone si réglé) ;
  • `/evenement` : le même panneau, en privé, partout où les commandes sont
    permises ;
  • les écrans privés : calendrier (image), cadeau, boutique — sans jamais
    dire que le cadeau dépend de la petite fille (secret de l'auteur).

Règles : `seasonal_service` ; écritures : `use_cases/seasonal` (atomiques).
Les sucres d'orge tombent dans `EncounterService.apply_rewards`, les
bénédictions du Nouvel An passent par `offering.active_blessings`.
"""

from __future__ import annotations

import asyncio
import io
import logging
from datetime import UTC, datetime, timedelta

import discord
from discord import app_commands
from discord.ext import commands, tasks

from app.application.use_cases import seasonal
from app.bot.cogs._mixins import BetaChannelOnlyMixin
from app.bot.cogs.channel_guides_cog import pin_message
from app.bot.cogs.rules_cog import same_panel
from app.bot.embeds import seasonal_embeds as se
from app.bot.rendering.advent_calendar import render_advent
from app.bot.views.seasonal_views import AdventView, GiftView, SeasonalPanelView, ShopView
from app.domain.services import seasonal_service as ss
from app.infrastructure.config.settings import settings
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.repositories.seasonal_repository import SeasonalRepository
from app.infrastructure.db.session import get_db_session
from app.infrastructure.offering import offering_loader

_logger = logging.getLogger("sakura.seasonal")
PANEL_KEY = "panel"
#: Le panneau est revérifié au moins aussi souvent (et dès que ce qui se passe change).
PANEL_REFRESH = timedelta(minutes=30)
ADVENT_FILE = "avent.png"


def panel_buttons(content: ss.SeasonalContent, now: datetime) -> tuple[tuple[str, ...], str]:
    """Les boutons utiles aujourd'hui (et le libellé de la boutique)."""
    today = ss.paris_day(now)
    buttons = []
    a, c = content.advent, content.christmas
    if a is not None and a.enabled and a.size and today <= a.end:
        buttons.append("advent")
    if c is not None and c.enabled and today <= c.claim_until:
        buttons.append("gift")
    shop = pick_shop(content, today)
    if shop is not None and today <= shop.closes:
        buttons.append("shop")
    return tuple(buttons), (shop.name if shop is not None else "Boutique")


def pick_shop(content: ss.SeasonalContent, today) -> ss.EventShop | None:
    """La boutique ouverte, sinon la prochaine, sinon la dernière."""
    shops = [s for s in content.shops if s.enabled]
    opened = [s for s in shops if s.is_open(today)]
    if opened:
        return opened[0]
    coming = sorted((s for s in shops if s.opens > today), key=lambda s: s.opens)
    if coming:
        return coming[0]
    return max(shops, key=lambda s: s.closes, default=None)


class SeasonalCog(BetaChannelOnlyMixin, commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.bot.add_view(SeasonalPanelView())
        self._signature: str | None = None
        self._panel_checked: datetime | None = None
        self.tick.start()

    def cog_unload(self) -> None:
        self.tick.cancel()

    # ------------------------------------------------------------- base --
    @staticmethod
    def _player_id(user) -> int:
        with get_db_session() as session:
            profile = PlayerRepository(session).get_or_create_by_discord_id(
                discord_id=user.id, username=user.name, display_name=user.display_name)
            return profile.player.id

    def _advent(self, user, open_door: bool = False):
        player_id = self._player_id(user)
        result = None
        with get_db_session() as session:
            if open_door:
                result = seasonal.open_advent_door(session, player_id)
            status = seasonal.advent_status(session, player_id)
        image = render_advent(status, user.display_name) if status is not None else None
        return result, status, image

    def _gift(self, user, open_gift: bool = False):
        player_id = self._player_id(user)
        result = None
        with get_db_session() as session:
            if open_gift:
                result = seasonal.open_christmas_gift(session, player_id)
            return result, seasonal.christmas_status(session, player_id)

    def _shop(self, user, code: str, item: str | None = None, quantity: int = 0):
        player_id = self._player_id(user)
        result = None
        with get_db_session() as session:
            if item:
                result = seasonal.buy(session, player_id, code, item, quantity)
            return result, seasonal.shop_status(session, player_id, code)

    # ---------------------------------------------------------- écrans --
    async def show_advent(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        _, status, image = await asyncio.to_thread(self._advent, interaction.user)
        if status is None:
            await interaction.followup.send("🎄 Pas de calendrier de l'Avent en ce moment.", ephemeral=True)
            return
        await interaction.followup.send(
            embed=se.build_advent_embed(status, interaction.user.display_name),
            file=discord.File(io.BytesIO(image), filename=ADVENT_FILE),
            view=AdventView(self, interaction.user.id, status), ephemeral=True)

    async def open_advent(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        result, status, image = await asyncio.to_thread(self._advent, interaction.user, True)
        if status is None:
            await interaction.edit_original_response(content=result.message if result else "—",
                                                     embed=None, attachments=[], view=None)
            return
        embed = se.build_advent_embed(status, interaction.user.display_name,
                                      granted=result.granted if result and result.ok else None)
        await interaction.edit_original_response(
            content=None if result is None or result.ok else result.message, embed=embed,
            attachments=[discord.File(io.BytesIO(image), filename=ADVENT_FILE)],
            view=AdventView(self, interaction.user.id, status))

    async def show_gift(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        _, status = await asyncio.to_thread(self._gift, interaction.user)
        if status is None:
            await interaction.followup.send("🎅 Pas de Noël au programme en ce moment.", ephemeral=True)
            return
        await interaction.followup.send(embed=se.build_christmas_embed(status),
                                        view=GiftView(self, interaction.user.id, status), ephemeral=True)

    async def open_gift(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        result, status = await asyncio.to_thread(self._gift, interaction.user, True)
        if status is None:
            await interaction.edit_original_response(content=result.message if result else "—", embed=None, view=None)
            return
        embed = se.build_christmas_embed(status, granted=result.granted if result and result.ok else None)
        await interaction.edit_original_response(
            content=None if result is None or result.ok else result.message, embed=embed,
            view=GiftView(self, interaction.user.id, status))

    async def show_shop(self, interaction: discord.Interaction, code: str | None = None,
                        selected: str | None = None, edit: bool = False) -> None:
        if code is None:
            shop = pick_shop(seasonal.content(), ss.paris_day())
            if shop is None:
                await interaction.response.send_message("🎁 Pas de boutique d'événement en ce moment.",
                                                        ephemeral=True)
                return
            code = shop.code
        if edit:
            await interaction.response.defer()
        else:
            await interaction.response.defer(ephemeral=True, thinking=True)
        _, status = await asyncio.to_thread(self._shop, interaction.user, code)
        if status is None:
            await interaction.followup.send("🎁 Cette boutique n'existe plus.", ephemeral=True)
            return
        embed = se.build_shop_embed(status)
        view = ShopView(self, interaction.user.id, status, selected)
        if edit:
            await interaction.edit_original_response(embed=embed, view=view)
        else:
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    async def buy(self, interaction: discord.Interaction, code: str, item: str | None, quantity: int) -> None:
        await interaction.response.defer()
        if not item or quantity < 1:
            return
        result, status = await asyncio.to_thread(self._shop, interaction.user, code, item, quantity)
        if status is None:
            return
        await interaction.edit_original_response(
            embed=se.build_shop_embed(status, result.message if result else ""),
            view=ShopView(self, interaction.user.id, status, item))

    # ---------------------------------------------------------- commande --
    @app_commands.command(name="evenement",
                          description="Les événements du moment : calendrier de l'Avent, cadeau de Noël, boutique…")
    async def evenement(self, interaction: discord.Interaction) -> None:
        content = seasonal.content()
        now = datetime.now(UTC)
        buttons, shop_label = panel_buttons(content, now)
        await interaction.response.send_message(
            embed=se.build_panel_embed(content, ss.happening(content, now)),
            view=SeasonalPanelView(buttons, shop_label), ephemeral=True)

    # -------------------------------------------------- salon des événements --
    def _announced(self) -> set[str]:
        with get_db_session() as session:
            return SeasonalRepository(session).announced()

    def _mark(self, key: str, channel_id: int | None = None, message_id: int | None = None) -> None:
        with get_db_session() as session:
            SeasonalRepository(session).mark_announced(key, channel_id, message_id)
            session.commit()

    def _panel_message_id(self) -> tuple[int | None, int | None]:
        with get_db_session() as session:
            row = SeasonalRepository(session).get_announcement(PANEL_KEY)
            return (row.channel_id, row.message_id) if row is not None else (None, None)

    def _item_name(self, code: str) -> str:
        with get_db_session() as session:
            return seasonal.item_names(session, [code]).get(code, code)

    async def announcement_embed(self, content: ss.SeasonalContent, a: ss.Announcement) -> discord.Embed | None:
        if a.kind == "advent" and content.advent is not None:
            return se.build_advent_announcement(content.advent)
        if a.kind == "drop":
            drop = next((d for d in content.drops if d.code == a.ref), None)
            if drop is not None:
                return se.build_drop_announcement(drop, await asyncio.to_thread(self._item_name, drop.item))
        if a.kind == "christmas" and content.christmas is not None:
            shops = [s for s in content.shops if s.enabled and s.opens == content.christmas.gift_day]
            return se.build_christmas_announcement(content.christmas, shops)
        if a.kind == "shop":
            shop = content.shop(a.ref)
            if shop is not None:
                return se.build_shop_announcement(shop)
        if a.kind == "new_year" and content.new_year is not None:
            return se.build_new_year_announcement(content.new_year, offering_loader.list_deities())
        return None

    async def post_announcements(self, channel, content: ss.SeasonalContent, now: datetime) -> list[str]:
        done = await asyncio.to_thread(self._announced)
        posted = []
        for a in ss.due(content, now, done):
            embed = await self.announcement_embed(content, a)
            if embed is None:
                continue
            extra = {}
            if a.kind == "new_year" and content.new_year is not None and content.new_year.mention_everyone:
                extra = {"content": "@everyone", "allowed_mentions": discord.AllowedMentions(everyone=True)}
            if a.kind != "new_year":
                buttons, shop_label = panel_buttons(content, now)
                if buttons:
                    extra["view"] = SeasonalPanelView(buttons, shop_label)
            try:
                message = await channel.send(embed=embed, **extra)
            except discord.HTTPException:
                _logger.warning("annonce %s impossible", a.key, exc_info=True)
                continue
            await asyncio.to_thread(self._mark, a.key, channel.id, message.id)
            posted.append(a.key)
            _logger.info("annonce saisonnière postée : %s", a.key)
        return posted

    def _has_events(self, content: ss.SeasonalContent) -> bool:
        return any((content.advent, content.christmas, content.new_year, content.drops, content.shops))

    async def keep_panel(self, channel, content: ss.SeasonalContent, now: datetime, force: bool = False) -> str:
        """Le panneau épinglé : posté s'il manque, réécrit quand ce qui se
        passe change. Renvoie "posté", "mis à jour", "inchangé" ou "échec"."""
        happening = ss.happening(content, now)
        signature = happening.signature()
        due_check = self._panel_checked is None or now - self._panel_checked >= PANEL_REFRESH
        if not force and signature == self._signature and not due_check:
            return "inchangé"
        embed = se.build_panel_embed(content, happening)
        buttons, shop_label = panel_buttons(content, now)
        view = SeasonalPanelView(buttons, shop_label)
        channel_id, message_id = await asyncio.to_thread(self._panel_message_id)
        message = None
        if message_id and channel_id == channel.id:
            try:
                message = await channel.fetch_message(message_id)
            except discord.NotFound:
                message = None
            except discord.HTTPException:
                return "échec"
        try:
            if message is None:
                message = await channel.send(embed=embed, view=view)
                await pin_message(channel, message, self.bot.user.id)
                await asyncio.to_thread(self._mark, PANEL_KEY, channel.id, message.id)
                outcome = "posté"
            elif signature != self._signature or not same_panel(message, embed):
                await message.edit(embed=embed, view=view)
                if not message.pinned:
                    await pin_message(channel, message, self.bot.user.id)
                outcome = "mis à jour"
            else:
                outcome = "inchangé"
        except discord.HTTPException:
            _logger.warning("panneau des événements impossible", exc_info=True)
            return "échec"
        self._signature = signature
        self._panel_checked = now
        return outcome

    @tasks.loop(minutes=1)
    async def tick(self) -> None:
        try:
            content = seasonal.content()
            if not self._has_events(content) or not settings.event_channel_id:
                return
            channel = self.bot.get_channel(settings.event_channel_id)
            if channel is None:
                return
            now = datetime.now(UTC)
            if await self.post_announcements(channel, content, now):
                await self.keep_panel(channel, content, now, force=True)
            else:
                outcome = await self.keep_panel(channel, content, now)
                if outcome not in ("inchangé",):
                    _logger.info("panneau des événements : %s", outcome)
        except Exception:  # noqa: BLE001 — la boucle ne s'arrête jamais
            _logger.exception("boucle des événements saisonniers")

    @tick.before_loop
    async def _wait_ready(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SeasonalCog(bot))
