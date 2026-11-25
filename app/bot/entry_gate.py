"""Porte d'entrée du serveur, côté bot (25/11/2026, demande de l'auteur).

Pas d'avant-première avant le lancement d'une saison :
  • « testeurs » : un nouveau venu ne peut plus accepter le règlement (donc ni
    Rang F, ni tutoriel) ; ceux qui l'ont déjà accepté continuent ;
  • « fermee »   : plus personne ne joue (admins exceptés) ; les rangs et
    Aventurier sont retirés, chacun ne voit plus que l'accueil et le règlement,
    et aucun rattrapage ne les redonne tant que la porte reste fermée ;
  • « ouverte »  : le parcours normal (rouvrir rend les rôles aussitôt).
`/admin porte` la règle ; le lancement de la saison la rouvre (la table est
vidée par `reset_season`, et `forget` relit l'état).
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime

import discord

from app.application.use_cases import entry_gate as gate_uc
from app.application.use_cases.entry_gate import CLOSED, MODES, OPEN, TESTERS, Gate  # noqa: F401
from app.infrastructure.config.settings import settings
from app.infrastructure.db.session import get_db_session

_logger = logging.getLogger(__name__)

REASON = "Porte d'entrée fermée avant le lancement de la saison"
MODE_LABELS = {
    OPEN: "🟢 ouverte — tout le monde peut entrer",
    TESTERS: "🟡 testeurs seulement — les nouveaux attendent l'ouverture",
    CLOSED: "🔴 fermée — tout le monde attend l'ouverture",
}

#: Relue au plus toutes les minutes : un changement fait hors du bot (site,
#: script sur le VPS) est suivi sans redémarrage.
CACHE_SECONDS = 60.0
_cache: dict[str, Gate] = {}
_read_at: dict[str, float] = {}


def _read() -> Gate:
    with get_db_session() as session:
        return gate_uc.read(session)


def current() -> Gate:
    """L'état de la porte (gardé en mémoire ; une base illisible = ouverte :
    le jeu ne se ferme pas sur une panne)."""
    if "gate" not in _cache or time.monotonic() - _read_at.get("gate", 0.0) > CACHE_SECONDS:
        try:
            _cache["gate"] = _read()
            _read_at["gate"] = time.monotonic()
        except Exception:  # noqa: BLE001
            _logger.exception("porte : lecture impossible, état précédent gardé")
            return _cache.get("gate", Gate())
    return _cache["gate"]


def forget() -> None:
    """Relire la porte en base (après un reset de saison)."""
    _cache.pop("gate", None)


def is_admin(user_id: int) -> bool:
    return user_id in settings.admin_ids


def waiting_text(gate: Gate | None = None) -> str:
    gate = gate or current()
    when = ""
    if gate.opens_at is not None:
        ts = int(gate.opens_at.timestamp())
        when = f" le <t:{ts}:F> (<t:{ts}:R>)"
    return (f"🌸 Les portes du Grand Cerisier ouvriront{when}. "
            "Reviens à ce moment-là : la saison commencera pour tout le monde en même temps !")


def can_accept(discord_id: int, *, accepted: bool) -> bool:
    """Peut-il accepter le règlement (c'est-à-dire entrer) ?"""
    return is_admin(discord_id) or current().lets_in(accepted=accepted)


def blocks(discord_id: int) -> bool:
    """Porte fermée : toute action du jeu est refusée (admins exceptés)."""
    return current().mode == CLOSED and not is_admin(discord_id)


def gives_roles() -> bool:
    """Les rôles du parcours se donnent-ils (restauration, rattrapage) ?"""
    return current().mode != CLOSED


async def refuse(interaction: discord.Interaction) -> None:
    """Répond en privé que la porte est fermée."""
    try:
        if interaction.response.is_done():
            await interaction.followup.send(waiting_text(), ephemeral=True)
        else:
            await interaction.response.send_message(waiting_text(), ephemeral=True)
    except discord.HTTPException:
        pass


async def lock_out(guild) -> tuple[int, list[str]]:
    """Porte fermée : chaque membre (admins et bots exceptés) perd ses rangs et
    Aventurier. Renvoie (membres renvoyés à l'entrée, échecs)."""
    from app.bot import access

    journey = access.journey_role_ids()
    done, failed = 0, []
    for member in list(guild.members):
        if getattr(member, "bot", False) or is_admin(member.id):
            continue
        held = [role for role in member.roles if role.id in journey]
        if not held:
            continue
        try:
            await member.remove_roles(*held, reason=REASON)
        except discord.DiscordException as exc:
            failed.append(f"{getattr(member, 'display_name', member.id)} ({exc})")
            continue
        done += 1
    return done, failed


async def set_mode(guild, mode: str, opens_at: datetime | None = None) -> str:
    """Change l'état de la porte et en tire les conséquences sur les rôles.
    Renvoie un compte rendu."""
    from app.bot import access

    def _write() -> Gate:
        with get_db_session() as session:
            return gate_uc.write(session, mode, opens_at)

    gate = await asyncio.to_thread(_write)
    _cache["gate"], _read_at["gate"] = gate, time.monotonic()
    report = f"Porte : {MODE_LABELS[mode]}."
    if guild is None:
        return report + " (serveur introuvable : rôles non modifiés)"
    if mode == CLOSED:
        done, failed = await lock_out(guild)
        report += f" {done} membre(s) renvoyé(s) à l'entrée (rangs et Aventurier retirés)"
        report += f", {len(failed)} échec(s) : {', '.join(failed[:5])}." if failed else "."
    else:
        ranks, adventurers = await access.reconcile(guild)
        if ranks or adventurers:
            report += f" Rôles rendus : {ranks} rang(s), {adventurers} Aventurier."
    return report
