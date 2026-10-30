"""Cog `/lune` : le ciel de Paris et ses événements (30/10/2026, idée de
l'auteur). Pleine lune, lune de sang, nuit noire et éclipses changent les
monstres des zones (règles : `lunar_service`, ciel : `astronomy`).

Annonces dans le salon général et les salons de zone : un rappel quelques
heures avant (sauf la nuit noire), le lever de l'événement, sa fin.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands, tasks

from app.bot.cogs._mixins import BetaChannelOnlyMixin
from app.domain.services import astronomy, lunar_service
from app.infrastructure.config.settings import settings
from app.infrastructure.encounters.farm_zone_loader import list_zone_channels
from app.infrastructure.pacing.pacing_loader import get_pacing

_logger = logging.getLogger("sakura.lunar")
_PARIS = ZoneInfo("Europe/Paris")
#: Rappel avant un événement (la nuit noire n'en a pas : rien à préparer).
REMINDER_BEFORE = timedelta(hours=3)
#: Un événement déjà commencé depuis plus longtemps n'est plus annoncé
#: (redémarrage du bot en pleine nuit de pleine lune).
LATE_ANNOUNCE = timedelta(minutes=20)
_COLORS = {"pleine_lune": (235, 225, 170), "lune_de_sang": (190, 30, 45), "nouvelle_lune": (60, 60, 90),
           "eclipse_lunaire": (150, 60, 40), "eclipse_solaire": (40, 30, 30)}


def _ts(when: datetime, style: str = "f") -> str:
    return f"<t:{int(when.timestamp())}:{style}>"


def _event_line(event: lunar_service.LunarEvent) -> str:
    detail = f" ({event.detail})" if event.detail else ""
    return (f"**{event.label}**{detail} — {_ts(event.start)} → {_ts(event.end, 't')} ({_ts(event.start, 'R')})\n"
            f"↳ {lunar_service.effects_text(event.rule)}")


def build_moon_embed(now: datetime | None = None) -> discord.Embed:
    now = now or datetime.now(UTC)
    rules = get_pacing().lunar
    fraction = astronomy.phase_fraction(now)
    active = lunar_service.active_event(now, rules)
    color = _COLORS.get(active.code, (120, 130, 200)) if active else (120, 130, 200)
    embed = discord.Embed(
        title=f"{lunar_service.phase_emoji(fraction)} Le ciel de Paris",
        description=(f"**{lunar_service.phase_name(fraction)}**, éclairée à "
                     f"{round(astronomy.illumination(now) * 100)} %.\n"
                     "La lune change les monstres des zones : plus forts, mais bien plus riches."),
        color=discord.Color.from_rgb(*color),
    )
    if active is not None:
        embed.add_field(name=f"En ce moment : {active.label}",
                        value=(f"*{active.kind.story}*\n{lunar_service.effects_text(active.rule)}"
                               f"\nJusqu'à {_ts(active.end, 't')} ({_ts(active.end, 'R')})."),
                        inline=False)
    coming = [e for e in lunar_service.upcoming(now, rules, days=120) if e is not active and e.start > now]
    if coming:
        embed.add_field(name="📅 À venir", value="\n".join(_event_line(e) for e in coming[:5]), inline=False)
    eclipses = [e for e in lunar_service.upcoming(now, rules, days=3 * 365)
                if e.code.startswith("eclipse") and e.start > now]
    if eclipses:
        embed.add_field(name="🔭 Prochaines éclipses visibles de Paris",
                        value="\n".join(f"{e.label} — {_ts(e.start, 'D')} ({e.detail})" for e in eclipses[:4]),
                        inline=False)
    rise, sets = astronomy.sun_times(now.replace(hour=11, minute=0, second=0, microsecond=0))
    if rise and sets:
        embed.set_footer(text=f"Calculé pour Paris · soleil levé de {rise.astimezone(_PARIS):%H:%M} "
                              f"à {sets.astimezone(_PARIS):%H:%M} · une pleine lune sur "
                              f"{lunar_service.BLOOD_MOON_EVERY} est une lune de sang")
    return embed


def build_event_embed(event: lunar_service.LunarEvent, phase: str) -> discord.Embed:
    """Annonce : `phase` = « soon », « start » ou « end »."""
    kind = event.kind
    detail = f" ({event.detail})" if event.detail else ""
    if phase == "soon":
        title = f"{kind.emoji} {kind.name} ce soir" if event.start.astimezone(_PARIS).hour >= 12 else f"{kind.emoji} {kind.name} bientôt"
        text = (f"{kind.story}\nElle commence {_ts(event.start, 'R')} ({_ts(event.start, 't')}){detail} : "
                f"{lunar_service.effects_text(event.rule)}.")
    elif phase == "start":
        title = f"{kind.emoji} {kind.name} !"
        text = (f"*{kind.story}*\n**{lunar_service.effects_text(event.rule)}** dans toutes les zones{detail}, "
                f"jusqu'à {_ts(event.end, 't')}.")
    else:
        title = f"{kind.emoji} Fin : {kind.name}"
        text = "Le ciel redevient calme : les monstres retrouvent leur force habituelle."
    return discord.Embed(title=title, description=text,
                         color=discord.Color.from_rgb(*_COLORS.get(event.code, (120, 130, 200))))


class LunarCog(BetaChannelOnlyMixin, commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._announced: set[tuple[str, str, str]] = set()
        self._current: lunar_service.LunarEvent | None = None
        self._first_tick = True
        self.sky_loop.start()

    def cog_unload(self) -> None:
        self.sky_loop.cancel()

    async def _announce(self, embed: discord.Embed, zones: bool) -> None:
        targets = set(list_zone_channels()) if zones else set()
        if settings.rank_announce_channel_id:
            targets.add(settings.rank_announce_channel_id)
        for channel_id in targets:
            channel = self.bot.get_channel(channel_id)
            if channel is None:
                continue
            try:
                await channel.send(embed=embed)
            except discord.HTTPException:
                _logger.warning("annonce lunaire impossible dans %s", channel_id)

    def _once(self, event: lunar_service.LunarEvent, phase: str) -> bool:
        key = (event.code, event.start.isoformat(), phase)
        if key in self._announced:
            return False
        self._announced.add(key)
        return True

    @tasks.loop(minutes=1)
    async def sky_loop(self) -> None:
        try:
            now = datetime.now(UTC)
            rules = get_pacing().lunar
            active, coming = await asyncio.to_thread(
                lambda: (lunar_service.active_event(now, rules),
                         lunar_service.upcoming(now, rules, days=2)))
            first, self._first_tick = self._first_tick, False
            previous = self._current
            if previous is not None and (active is None or active.code != previous.code
                                         or active.start != previous.start):
                if self._once(previous, "end"):
                    await self._announce(build_event_embed(previous, "end"), zones=False)
            self._current = active
            if active is not None and (not first or now - active.start < LATE_ANNOUNCE) \
                    and (previous is None or previous.start != active.start or previous.code != active.code):
                if self._once(active, "start"):
                    await self._announce(build_event_embed(active, "start"), zones=True)
            for event in coming:
                if (event.code != "nouvelle_lune" and now < event.start <= now + REMINDER_BEFORE
                        and self._once(event, "soon")):
                    await self._announce(build_event_embed(event, "soon"), zones=False)
        except Exception:  # noqa: BLE001
            _logger.exception("boucle lunaire")

    @sky_loop.before_loop
    async def _before(self) -> None:
        await self.bot.wait_until_ready()

    @app_commands.command(name="lune", description="Le ciel de Paris : phase de la lune, pleines lunes, lunes de sang, éclipses")
    async def lune(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        embed = await asyncio.to_thread(build_moon_embed)
        await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(LunarCog(bot))
