"""Cog `/defi` : défis de rôle quotidiens (DPS / Tank / Soutien).

Remplace les duels JcJ (décision de l'auteur, 25/10/2026). Règles dans
`role_trial_service`, persistance et clôture dans `use_cases/role_trials`.

  • `/defi`            : programme du jour, tes scores, ta semaine ;
  • `/defi role:<…>`   : un essai (résultat immédiat, déterministe) — le
                         premier de la journée rapporte un peu d'or ;
  • minuit (Paris)     : programme du jour posté dans le salon des défis ;
  • dimanche 20 h      : clôture — or du podium, titres de la semaine, annonce.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, time, timedelta

import discord

from app.shared.formatters import format_int
from discord import app_commands
from discord.ext import commands, tasks

from app.application.use_cases import role_trials
from app.bot.cogs._mixins import BetaChannelOnlyMixin
from app.bot.embeds.role_trial_embeds import (
    build_attempt_embed,
    build_day_announcement,
    build_day_embed,
    build_results_embed,
)
from app.domain.services import role_trial_service as rts
from app.infrastructure.config.settings import settings
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.repositories.role_trial_repository import RoleTrialRepository
from app.infrastructure.db.session import get_db_session

_logger = logging.getLogger("sakura.role_trials")

_MIDNIGHT = time(hour=0, minute=0, tzinfo=rts.TRIAL_TZ)
_ROLE_CHOICES = [
    app_commands.Choice(name="⚔️ DPS — dégâts infligés", value="dps"),
    app_commands.Choice(name="🛡️ Tank — dégâts encaissés", value="tank"),
    app_commands.Choice(name="💚 Soutien — PV soignés", value="soutien"),
]



def _trials_screen(day, mine, week, first_gold, closed, seed: int):
    """Les défis du jour en image (DA du bot, 21/11/2026) ; None = embed texte."""
    from app.bot.embeds.role_trial_embeds import _day_label, _place
    from app.bot.embeds.screen_embed import image_embed
    from app.bot.rendering import screens

    cards = []
    for role in rts.ROLES:
        variant = rts.variant_of_day(day, role)
        entry = (mine or {}).get(role)
        best = ""
        if entry:
            score, attempts, place, total = entry
            best = f"{format_int(score)} · {attempts} essai{'s' if attempts > 1 else ''} · {_place(place)} sur {total}"
        cards.append(screens.TrialCard(role, rts.ROLE_LABELS[role], variant.name, variant.description, best))
    week_text = ""
    if week is not None:
        parts = []
        for key, label in [*rts.ROLE_LABELS.items(), (rts.GENERAL, rts.GENERAL_LABEL)]:
            entry = week.get(key)
            parts.append(f"{label} " + ("—" if entry is None else f"{_place(entry[0])} ({format_int(round(entry[1]))})"))
        week_text = " · ".join(parts)
    if closed:
        banner = "🏁 Résultats de la semaine tombés : nouveaux défis à minuit"
    elif mine:
        banner = "✅ Récompense du premier défi prise : à demain !"
    else:
        banner = f"🎁 Ton premier défi du jour te rapporte {format_int(first_gold or 0)} or"
    return image_embed(screens.compose_trials, f"defi_{seed}", discord.Color.teal(),
                       title=f"🎯 Défis du {_day_label(day)}",
                       subtitle="Trois épreuves, une par rôle — même adversaire pour tout le serveur",
                       cards=cards, week=week_text, banner=banner, seed=seed)

class RoleTrialCog(BetaChannelOnlyMixin, commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.daily_announce_loop.start()
        self.settle_loop.start()

    def cog_unload(self) -> None:
        self.daily_announce_loop.cancel()
        self.settle_loop.cancel()

    # ------------------------------------------------------------ lecture --
    def _overview(self, user) -> tuple:
        now = datetime.now(UTC)
        day = rts.trial_day(now)
        with get_db_session() as session:
            profile = PlayerRepository(session).get_or_create_by_discord_id(
                discord_id=user.id, username=user.name, display_name=user.display_name,
            )
            pid = profile.player.id
            repo = RoleTrialRepository(session)
            mine = {}
            for role, (score, attempts) in repo.player_day(pid, day).items():
                board = repo.day_scores(day, role)
                place = next((i + 1 for i, (p, _) in enumerate(board) if p == pid), len(board))
                mine[role] = (score, attempts, place, len(board))
            standings = role_trials.week_standings(session, rts.week_start(day))
            week = role_trials.player_week(standings, pid)
            first_gold = rts.first_of_day_gold(profile.progression.level)
        return day, mine, week, first_gold, rts.is_closed(now)

    def _attempt(self, user, role: str):
        now = datetime.now(UTC)
        with get_db_session() as session:
            profile = PlayerRepository(session).get_or_create_by_discord_id(
                discord_id=user.id, username=user.name, display_name=user.display_name,
            )
            return role_trials.run_attempt(session, profile, role, now)

    # --------------------------------------------------------- commande --
    @app_commands.command(
        name="defi",
        description="Défis de rôle du jour (DPS, Tank, Soutien) — meilleur score gardé",
    )
    @app_commands.describe(role="Lance un essai — laisse vide pour voir le programme et tes scores")
    @app_commands.choices(role=_ROLE_CHOICES)
    async def defi(self, interaction: discord.Interaction,
                   role: app_commands.Choice[str] | None = None) -> None:
        await interaction.response.defer()
        if role is None:
            day, mine, week, first_gold, closed = await asyncio.to_thread(self._overview, interaction.user)
            screen = await asyncio.to_thread(_trials_screen, day, mine, week, first_gold, closed, interaction.user.id)
            if screen is not None:
                await interaction.followup.send(embed=screen[0], file=screen[1])
                return
            embed = build_day_embed(day, mine, week, first_gold)
            if closed:
                embed.description = ("🏁 Les résultats de la semaine sont tombés : "
                                     "nouveaux défis à minuit.")
            await interaction.followup.send(embed=embed)
            return
        if rts.is_closed(datetime.now(UTC)):
            await interaction.followup.send(
                f"🏁 Les défis de la semaine sont clos depuis {rts.RESULTS_HOUR} h : "
                "nouveaux défis à minuit.")
            return
        outcome = await asyncio.to_thread(self._attempt, interaction.user, role.value)
        await interaction.followup.send(embed=build_attempt_embed(outcome))

    # ------------------------------------------------------------ boucles --
    async def _channel(self):
        channel_id = settings.role_trial_channel_id
        if not channel_id:
            return None
        channel = self.bot.get_channel(channel_id)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(channel_id)
            except discord.HTTPException:
                _logger.warning("Salon des défis %s introuvable", channel_id)
                return None
        return channel

    @tasks.loop(time=_MIDNIGHT)
    async def daily_announce_loop(self) -> None:
        """Minuit : le programme du jour dans le salon des défis."""
        try:
            channel = await self._channel()
            if channel is not None:
                await channel.send(embed=build_day_announcement(rts.trial_day(datetime.now(UTC))))
        except Exception:
            _logger.exception("annonce des défis du jour échouée")

    @daily_announce_loop.before_loop
    async def _before_announce(self) -> None:
        await self.bot.wait_until_ready()

    def _settle_due(self) -> list[tuple]:
        """Clôture les semaines échues pas encore clôturées : la semaine en
        cours si on a passé dimanche 20 h, et la précédente (rattrapage si le
        bot était éteint ce soir-là). → [(lundi, résultats)] à annoncer."""
        now = datetime.now(UTC)
        current = rts.week_start(rts.trial_day(now))
        due = [current - timedelta(days=7)]
        if now >= rts.results_at(current):
            due.append(current)
        out = []
        with get_db_session() as session:
            for week in due:
                results = role_trials.settle_week(session, week)
                if results is not None and any(results.values()):
                    out.append((week, results))
        return out

    @tasks.loop(minutes=10)
    async def settle_loop(self) -> None:
        """Dimanche 20 h : or du podium, titres de la semaine, annonce.
        Idempotent (table `role_trial_weeks`) : relancé toutes les 10 min."""
        try:
            settled = await asyncio.to_thread(self._settle_due)
            if not settled:
                return
            channel = await self._channel()
            for week, results in settled:
                _logger.info("Défis : semaine du %s clôturée", week)
                if channel is not None:
                    await channel.send(embed=build_results_embed(week, results))
        except Exception:
            _logger.exception("clôture des défis échouée")

    @settle_loop.before_loop
    async def _before_settle(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(RoleTrialCog(bot))
