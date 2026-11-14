"""Surveillance côté bot (01/11/2026) : ce que seul le bot voit, et ce qu'il
doit faire à heure fixe.

  • chaque interaction (commande, bouton, menu) va dans le tampon du journal,
    vidé toutes les 30 s (`telemetry.interactions`) ;
  • chaque arrivée sur le serveur est notée (avant même le profil) ;
  • toutes les 30 min, une PHOTO de chaque joueur, rang Discord compris
    (`application.monitoring.snapshots`) ;
  • toutes les heures, les ALERTES : historique mis à jour, et les nouvelles
    alertes graves envoyées en message privé aux admins (réglable dans
    Surveillance › Alertes) ;
  • le lundi matin, le rapport de la semaine écoulée, en message privé.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import UTC, datetime

import discord
from discord.ext import commands, tasks
from sqlalchemy import func, select

from app.bot.notifications import send_dm
from app.bot.rank_roles import current_rank
from app.domain.services.monitoring import kinds
from app.domain.services.monitoring.alerts import SEVERITY_LABELS
from app.domain.services.pacing_service import PARIS
from app.bot.embeds.limits import fit_lines
from app.infrastructure.config.settings import settings
from app.infrastructure.db.models.monitoring_model import GameEventModel
from app.infrastructure.db.models.player_model import PlayerModel
from app.infrastructure.db.session import get_db_session
from app.infrastructure.monitoring import telemetry

_logger = logging.getLogger("sakura.monitoring")

SEVERITY_ICONS = {"critique": "🔴", "serieux": "🟠", "attention": "🟡", "info": "🟣"}
REPORT_HOUR = 9           # rapport hebdomadaire : lundi, 9 h (Paris)
_DIGITS = re.compile(r"\d+")


def interaction_ref(interaction: discord.Interaction) -> str:
    """Ce que le joueur a fait, sans identifiant : « boss moi »,
    « bouton:encounter_join »…"""
    if interaction.type == discord.InteractionType.application_command:
        command = interaction.command
        if command is not None:
            return command.qualified_name
        return str((interaction.data or {}).get("name", "?"))
    if interaction.type == discord.InteractionType.autocomplete:
        return ""
    custom_id = str((interaction.data or {}).get("custom_id", "") or "")
    kind = "modal" if interaction.type == discord.InteractionType.modal_submit else "bouton"
    return f"{kind}:{_DIGITS.sub('', custom_id).strip(':_-')[:40] or 'vue'}"


class MonitoringCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.flush_loop.start()
        self.snapshot_loop.start()
        self.alert_loop.start()

    def cog_unload(self) -> None:
        self.flush_loop.cancel()
        self.snapshot_loop.cancel()
        self.alert_loop.cancel()
        self._flush()             # rien ne se perd à l'arrêt

    # ------------------------------------------------------------ journal
    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction) -> None:
        if interaction.user is None or interaction.user.bot:
            return
        ref = interaction_ref(interaction)
        if ref:
            telemetry.interactions.push(interaction.user.id, ref)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        if member.bot or (settings.discord_guild_id and member.guild.id != settings.discord_guild_id):
            return
        telemetry.interactions.push(member.id, "arrivee", kind=kinds.MEMBER_JOIN)

    @staticmethod
    def _flush() -> int:
        with get_db_session() as session:
            return telemetry.interactions.flush(session)

    @tasks.loop(seconds=30)
    async def flush_loop(self) -> None:
        try:
            if len(telemetry.interactions):
                await asyncio.to_thread(self._flush)
        except Exception:  # noqa: BLE001 — la boucle ne doit jamais mourir
            _logger.exception("flush_loop failed")

    # -------------------------------------------------------------- photos
    def _guild(self) -> discord.Guild | None:
        if settings.discord_guild_id:
            return self.bot.get_guild(settings.discord_guild_id)
        return self.bot.guilds[0] if self.bot.guilds else None

    def _ranks(self) -> dict[int, str]:
        """Rang Discord porté, par player_id (membres présents seulement)."""
        guild = self._guild()
        if guild is None:
            return {}
        with get_db_session() as session:
            ids = dict(session.execute(select(PlayerModel.discord_id, PlayerModel.id)).all())
        out = {}
        for discord_id, player_id in ids.items():
            member = guild.get_member(int(discord_id))
            if member is not None:
                out[player_id] = current_rank(member)
        return out

    @staticmethod
    def _snapshot(ranks: dict[int, str]) -> int:
        from app.application.monitoring.snapshots import take_snapshots

        with get_db_session() as session:
            count = take_snapshots(session, ranks)
            try:      # les vieux clics deviennent un total par joueur et par jour
                if telemetry.compact_interactions(session):
                    session.commit()
            except Exception:  # noqa: BLE001 — le ménage ne casse jamais les photos
                session.rollback()
                _logger.exception("résumé des anciens clics impossible")
            return count

    async def take_snapshots_now(self) -> int:
        """Une photo de chaque joueur, tout de suite (aussi au lancement d'une
        saison : le point de départ de chacun)."""
        return await asyncio.to_thread(self._snapshot, self._ranks())

    @tasks.loop(minutes=30)
    async def snapshot_loop(self) -> None:
        try:
            count = await self.take_snapshots_now()
            _logger.info("Surveillance : %d photos de joueurs", count)
        except Exception:  # noqa: BLE001
            _logger.exception("snapshot_loop failed")

    # -------------------------------------------------------------- alertes
    @staticmethod
    def _check_alerts() -> list[tuple[str, str, str, str]]:
        """Recalcule les alertes, met l'historique à jour et renvoie celles à
        envoyer (gravité, titre, message, clé) — marquées envoyées."""
        from app.application.monitoring import alerting, dataset

        with get_db_session() as session:
            ds = dataset.load(session, days=30, include_admins=False)
            alerting.sync(session, alerting.compute(ds))
            rows = alerting.to_notify(session)
            out = [(r.severity, r.title, r.message or "", r.key) for r in rows]
            now = datetime.now(UTC).replace(tzinfo=None)
            for r in rows:
                r.notified_at = now
            session.commit()
        return out

    async def _send_to_admins(self, content: str) -> None:
        for admin_id in settings.admin_ids:
            await send_dm(self.bot, admin_id, content)

    @tasks.loop(hours=1)
    async def alert_loop(self) -> None:
        try:
            fresh = await asyncio.to_thread(self._check_alerts)
            if fresh:
                order = list(SEVERITY_ICONS)
                fresh.sort(key=lambda a: order.index(a[0]) if a[0] in order else 9)
                # Le lien du site vient EN TÊTE : à partir de sept alertes, la
                # coupe à 2 000 caractères l'emportait avec la fin du message.
                head = [f"🚨 **Surveillance : {len(fresh)} nouvelle{'s' if len(fresh) > 1 else ''} alerte{'s' if len(fresh) > 1 else ''}**",
                        f"👉 {settings.webapp_base_url.rstrip('/')}/admin/monitoring/alerts"]
                alerts = [f"{SEVERITY_ICONS.get(severity, '•')} **{SEVERITY_LABELS.get(severity, severity)}** — {title}\n> {message[:180]}"
                          for severity, title, message, _ in fresh]
                budget = 1900 - sum(len(line) + 1 for line in head)
                await self._send_to_admins("\n".join(head) + "\n" + fit_lines(alerts, budget=budget, more="… et {n} autre(s)."))
            await self._weekly_report()
        except Exception:  # noqa: BLE001
            _logger.exception("alert_loop failed")

    async def _weekly_report(self) -> None:
        """Le lundi à partir de 9 h : le résumé de la semaine écoulée, une fois."""
        now = datetime.now(PARIS)
        if now.weekday() != 0 or now.hour < REPORT_HOUR:
            return
        week = now.date().isoformat()
        text = await asyncio.to_thread(self._report_text, week)
        if text:
            await self._send_to_admins(text)

    @staticmethod
    def _report_text(week: str) -> str | None:
        from app.application.monitoring import dataset, report

        with get_db_session() as session:
            sent = session.execute(select(GameEventModel.id).where(
                GameEventModel.kind == "report", GameEventModel.ref == week)).first()
            if sent is not None:
                return None
            data = report.weekly(session, weeks_ago=1)
            telemetry.record(session, "report", ref=week)
            session.commit()
            season_at = session.execute(select(func.max(GameEventModel.at)).where(
                GameEventModel.kind == kinds.SEASON_START)).scalar()
        if season_at is not None and dataset.to_local(season_at).date() > data["sunday"]:
            return None               # la semaine écoulée est d'avant la saison : rien à raconter
        lines = [f"📰 **Rapport de la semaine du {data['monday'].strftime('%d/%m')} au {data['sunday'].strftime('%d/%m')}**"]
        lines += [f"{icon} {text}" for icon, text in data["highlights"]] or ["Semaine calme."]
        link = f"👉 {settings.webapp_base_url.rstrip('/')}/admin/monitoring/report?week=1"
        return fit_lines(lines, budget=1900 - len(link), more="… et {n} autre(s) fait(s) marquant(s).") + "\n" + link

    @flush_loop.before_loop
    @snapshot_loop.before_loop
    @alert_loop.before_loop
    async def _before(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MonitoringCog(bot))
