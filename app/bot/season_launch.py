"""Lancement officiel d'une saison (`/admin lancer_saison`, 01/11/2026).

Demande de l'auteur : une commande pour lancer la saison — tout le monde
repart de zéro, la surveillance du site admin aussi.

Déroulé (`launch`) :
  1. les commandes des joueurs sont FERMÉES le temps du lancement (`allow`,
     branché sur l'arbre des commandes) et celles en cours ont quelques
     secondes pour finir — sinon une écriture commencée avant le reset
     pourrait reposer de vieilles valeurs après lui ;
  2. sauvegarde de la base — si elle échoue, on s'arrête là, rien n'est touché ;
  3. combats de zone annulés, world boss arrêté (son message supprimé),
     messages d'événements retirés ;
  4. `reset_season` (joueurs, tables de saison, surveillance), tout ou rien,
     et le repère « saison N » dans le journal ;
  5. rangs Discord remis au Rang F, première photo des joueurs ;
  6. les commandes rouvrent, l'annonce part dans le salon général.
"""

from __future__ import annotations

import asyncio
import io
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import discord
from sqlalchemy import select

from app.application.use_cases.reset_season import (
    SeasonResetReport,
    preview_season_reset,
    reset_season,
)
from app.domain.services.pacing_service import PARIS
from app.infrastructure.config.settings import settings
from app.infrastructure.db.backup import BackupError, backup_sqlite
from app.infrastructure.db.models.event_model import ActiveEventModel
from app.infrastructure.db.repositories.admin_command_repository import AdminCommandRepository
from app.infrastructure.db.repositories.world_boss_repository import WorldBossRepository
from app.infrastructure.db.session import get_db_session
from app.infrastructure.monitoring import telemetry

_logger = logging.getLogger("sakura.season")

#: Temps laissé aux commandes en cours avant le reset (secondes).
DRAIN_SECONDS = 3.0
SEASON_COLOR = discord.Color.from_rgb(255, 150, 195)
SEASON_IMAGE = "saison.png"
CLOSED_MESSAGE = ("🌸 Le Grand Cerisier se prépare pour la nouvelle saison : "
                  "réessaie dans une minute !")

#: Mention de l'annonce : valeur du choix → texte posté avant l'annonce.
PINGS = {"everyone": "@everyone", "here": "@here", "none": "", "off": None}
PING_LABELS = {"everyone": "avec @everyone", "here": "avec @here", "none": "sans mention", "off": "aucune annonce"}

_state = {"closed": False}
_lock = asyncio.Lock()


class LaunchError(RuntimeError):
    pass


def confirmation(season: int) -> str:
    return f"SAISON {season}"


def is_closed() -> bool:
    return _state["closed"]


async def allow(interaction: discord.Interaction) -> bool:
    """Contrôle global des commandes : pendant un lancement, seuls les admins
    passent (le joueur reçoit un mot d'attente)."""
    if not _state["closed"] or interaction.user.id in settings.admin_ids:
        return True
    if interaction.type is discord.InteractionType.application_command and not interaction.response.is_done():
        try:
            await interaction.response.send_message(CLOSED_MESSAGE, ephemeral=True)
        except discord.HTTPException:
            pass
    return False


# ------------------------------------------------------------------ aperçu
@dataclass
class Preview:
    report: SeasonResetReport
    encounters: int = 0
    boss: str | None = None
    events: int = 0


def preview(bot) -> Preview:
    """Ce que le lancement effacerait — sans rien modifier."""
    with get_db_session() as session:
        report = preview_season_reset(session)
        boss = WorldBossRepository(session).get_active()
        events = session.execute(select(ActiveEventModel.id).where(ActiveEventModel.status == "active")).all()
    encounter_cog = bot.get_cog("EncounterCog")
    return Preview(
        report=report,
        encounters=len(getattr(encounter_cog, "active_encounters", {}) or {}),
        boss=boss.name if boss is not None and boss.is_alive else None,
        events=len(events),
    )


# --------------------------------------------------------------- lancement
@dataclass
class LaunchResult:
    season: int
    backup: Path | None = None
    report: SeasonResetReport | None = None
    steps: list[tuple[bool, str]] = field(default_factory=list)
    announcement_url: str | None = None


async def _remove_event_messages(bot) -> int:
    """Retire les messages des événements en cours (coffre, petite fille,
    forge…) : leurs boutons ne mèneraient plus à rien."""
    with get_db_session() as session:
        rows = session.execute(select(ActiveEventModel.channel_id, ActiveEventModel.message_id)
                               .where(ActiveEventModel.status == "active")).all()
    removed = 0
    for channel_id, message_id in rows:
        channel = bot.get_channel(int(channel_id)) if channel_id else None
        if channel is None or not message_id:
            continue
        try:
            await (await channel.fetch_message(int(message_id))).delete()
            removed += 1
        except discord.HTTPException:
            pass
    return removed


def _reset(season: int) -> SeasonResetReport:
    with get_db_session() as session:
        return reset_season(session, queue_role_reset=False, season=season)


async def _reset_ranks(bot) -> tuple[bool, str]:
    bridge = bot.get_cog("AdminBridgeCog")
    if bridge is not None:
        return await bridge.reset_rank_roles()
    with get_db_session() as session:
        AdminCommandRepository(session).enqueue("reset_rank_roles")
        session.commit()
    return True, "remise au Rang F mise en file (le bot l'exécutera)."


async def launch(bot, season: int, ping: str = "everyone") -> LaunchResult:
    """Lance la saison `season` (cf. le déroulé en tête du module). Lève
    `LaunchError` si rien n'a pu commencer (sauvegarde impossible, lancement
    déjà en cours)."""
    if _lock.locked():
        raise LaunchError("Un lancement de saison est déjà en cours.")
    result = LaunchResult(season=season)
    async with _lock:
        _state["closed"] = True
        try:
            await asyncio.sleep(DRAIN_SECONDS)
            try:
                result.backup = await asyncio.to_thread(backup_sqlite, f"avant_saison_{season}")
            except BackupError as exc:
                raise LaunchError(f"{exc} Rien n'a été modifié.") from exc
            result.steps.append((True, f"Sauvegarde : `{result.backup.name}`"))

            encounter_cog = bot.get_cog("EncounterCog")
            if encounter_cog is not None:
                ok, msg = encounter_cog.force_end_encounter()
                result.steps.append((True, "Combats de zone : " + (msg if ok else "aucun en cours.")))
            boss_cog = bot.get_cog("WorldBossCog")
            if boss_cog is not None:
                ok, msg = await boss_cog.admin_stop_boss()
                result.steps.append((True, "World boss : " + (msg if ok else "aucun en cours.")))
            removed = await _remove_event_messages(bot)
            if removed:
                result.steps.append((True, f"Événements en cours retirés : {removed}."))

            telemetry.interactions.clear()
            # Sur la boucle du bot, d'un bloc : aucune commande ne s'intercale.
            result.report = _reset(season)
            cleared = result.report.cleared
            monitoring = sum(cleared.get(t, 0) for t in ("game_events", "player_daily_snapshots", "monitoring_alerts"))
            result.steps.append((True, f"{result.report.players} joueurs remis à zéro, surveillance vidée "
                                       f"({monitoring} lignes, + celles des joueurs)."))
            _logger.info("Saison %d lancée : %d joueurs remis à zéro (sauvegarde %s)",
                         season, result.report.players, result.backup)

            try:
                ok, msg = await _reset_ranks(bot)
            except Exception:  # noqa: BLE001 — la saison est lancée, on le signale
                _logger.exception("remise des rangs au Rang F impossible")
                ok, msg = False, "échec (voir les journaux du bot) — relancer depuis le site admin."
            result.steps.append((ok, f"Rangs Discord : {msg}"))
            monitoring_cog = bot.get_cog("MonitoringCog")
            if monitoring_cog is not None:
                try:
                    count = await monitoring_cog.take_snapshots_now()
                    result.steps.append((True, f"Surveillance : première photo de {count} joueurs."))
                except Exception:  # noqa: BLE001
                    _logger.exception("photo de départ impossible")
        finally:
            _state["closed"] = False

    if PINGS.get(ping) is not None:
        try:
            result.announcement_url = await announce(bot, season, PINGS[ping])
        except Exception:  # noqa: BLE001
            _logger.exception("annonce de la saison impossible")
        result.steps.append((result.announcement_url is not None,
                             "Annonce : " + ("postée." if result.announcement_url else "salon introuvable ou envoi refusé.")))
    return result


# ------------------------------------------------------------------ annonce
def build_announcement_embed(season: int) -> discord.Embed:
    from app.infrastructure.encounters.farm_zone_loader import list_zones

    tuto = f"<#{settings.tutorial_channel_id}>" if settings.tutorial_channel_id else "`/tuto`"
    zone = next((z for z in list_zones() if z.get("channel_id")), None)
    zone_txt = f"<#{zone['channel_id']}>" if zone else "la première zone"
    embed = discord.Embed(
        title=f"🌸 La saison {season} commence !",
        description=(
            "Le Grand Cerisier a refleuri et les registres de la guilde ont été effacés : "
            "**tout le monde repart du Rang F**, niveau 1, la bourse vide. La course recommence, "
            "et elle est la même pour tous.\n\n"
            "🌱 **Remis à zéro** : niveaux, or, équipement, arbre, titres, quêtes, tour, défis, "
            "affinités… et de **nouveaux talents élémentaires**, tirés pour chacun — la voyante a "
            "déjà sorti ses cartes.\n\n"
            "**Par où commencer ?**\n"
            f"1️⃣ Hana t'attend dans {tuto} : au bout, **3 Potions du Grand Cerisier** 🧪\n"
            "2️⃣ `/daily` chaque jour, `/stats` pour placer tes points\n"
            f"3️⃣ Les monstres sortent déjà dans {zone_txt} ⚔️\n\n"
            "Premier au Rang E, premier mythique, premier au sommet de la tour : "
            "**les classements sont vides**. À toi de les remplir."
        ),
        color=SEASON_COLOR,
    )
    embed.set_image(url=f"attachment://{SEASON_IMAGE}")
    embed.set_footer(text=f"Saison {season} · lancée le {datetime.now(PARIS):%d/%m/%Y} · bonne chasse ! 🌸")
    return embed


async def announce(bot, season: int, mention: str) -> str | None:
    """Poste l'annonce dans le salon général ; renvoie son lien."""
    from app.bot.cogs.onboarding_cog import build_join_view
    from app.bot.rendering.welcome_card import compose_season_card

    channel = bot.get_channel(settings.rank_announce_channel_id)
    if channel is None:
        return None
    files = []
    embed = build_announcement_embed(season)
    try:
        image = await asyncio.to_thread(compose_season_card, season)
        files.append(discord.File(io.BytesIO(image), filename=SEASON_IMAGE))
    except Exception:  # noqa: BLE001 — sans image, l'annonce part quand même
        _logger.exception("carte de la saison impossible")
        embed.set_image(url=None)
    guild_id = getattr(getattr(channel, "guild", None), "id", 0)
    message = await channel.send(
        content=mention or None, embed=embed, files=files, view=build_join_view(guild_id),
        allowed_mentions=discord.AllowedMentions(everyone=bool(mention), users=False, roles=False))
    return message.jump_url
