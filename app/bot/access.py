"""Le parcours d'arrivée sur Discord (08/11/2026, demande de l'auteur) :
les rôles des membres et les permissions des salons.

  • règlement accepté → Rang F (`rules_gate.accept`) ;
  • tutoriel fini ou passé → Aventurier (`tutorial_cog`) ;
  • retour d'un membre parti → ses rôles lui sont rendus (`on_member_join`) ;
  • filet de sécurité : `reconcile` (démarrage puis toutes les 30 min,
    `AccessCog`) donne ce qui manque. Rien n'est jamais RETIRÉ à un membre…
  • … sauf au lancement d'une saison (`reset_journey`, décision de l'auteur
    du 09/11/2026) : tout le monde repasse par le règlement et le tutoriel.

Les permissions des salons ne changent que sur demande, après un aperçu :
`/admin acces` ou `scripts/channel_access.py`. Règles : `access_plan`.
"""

from __future__ import annotations

import asyncio
import logging

import discord

from app.application.use_cases import member_access
from app.bot import access_plan as ap
from app.bot.rank_roles import ensure_start_rank_role, has_any_rank_role
from app.infrastructure.config.settings import settings
from app.infrastructure.db.session import get_db_session
from app.infrastructure.encounters.farm_zone_loader import list_zones

_logger = logging.getLogger(__name__)

REASON = "Parcours d'arrivée"
#: Nom du rôle quand on le crée (`scripts/channel_access.py --create-role`).
ADVENTURER_NAME = "⊰🧭⊱ Aventurier"
#: Attente maximale des rôles avant de répondre à un clic : une interaction
#: doit répondre en moins de 3 s ; si Discord traîne, les rôles suivent.
ROLE_WAIT = 2.0

_background: set[asyncio.Task] = set()
#: Augmente à chaque remise à zéro du parcours : un rattrapage ou un `restore`
#: qui a lu la base AVANT ne redonne rien APRÈS (ses états sont périmés).
_generation = 0


def general_channel_id() -> int:
    """Le salon général (annonces de rang, de saison…)."""
    return settings.rank_announce_channel_id or settings.beta_channel_id


def first_zone() -> dict | None:
    """La zone du Rang F (ouverte dès le règlement accepté)."""
    zones = [z for z in list_zones() if z.get("channel_id")]
    return next((z for z in zones if z.get("rank") == "F"), zones[0] if zones else None)


def channel_url(guild_id: int, channel_id: int) -> str:
    return f"https://discord.com/channels/{guild_id}/{channel_id}"


# ------------------------------------------------------------------ membres
def _state(discord_id: int) -> member_access.MemberAccess:
    with get_db_session() as session:
        return member_access.access(session, discord_id)


def _states() -> dict[int, member_access.MemberAccess]:
    with get_db_session() as session:
        return member_access.all_access(session)


def has_adventurer_role(member) -> bool:
    return any(role.id == settings.adventurer_role_id for role in member.roles)


async def grant_adventurer(member) -> bool:
    """Donne le rôle Aventurier. Vrai s'il vient d'être donné."""
    if not settings.adventurer_role_id or getattr(member, "bot", False) or has_adventurer_role(member):
        return False
    role = member.guild.get_role(settings.adventurer_role_id)
    if role is None:
        _logger.warning("rôle Aventurier %s introuvable sur le serveur", settings.adventurer_role_id)
        return False
    try:
        await member.add_roles(role, reason=f"{REASON} — l'aventure commence")
    except discord.DiscordException as exc:
        _logger.warning("Aventurier : échec pour %s : %s", member.id, exc)
        return False
    return True


async def restore(member) -> member_access.MemberAccess:
    """Donne à un membre les rôles de son parcours, sans jamais en retirer :
    un rang s'il a accepté le règlement, Aventurier s'il a aussi commencé
    l'aventure. Renvoie où il en est."""
    generation = _generation
    state = await asyncio.to_thread(_state, member.id)
    if state.accepted and not getattr(member, "bot", False) and generation == _generation:
        await ensure_start_rank_role(member)
        if state.adventurer and generation == _generation:
            await grant_adventurer(member)
    return state


async def member_of(client, user) -> discord.Member | None:
    """Le membre du serveur du jeu derrière un utilisateur (clic en MP compris)."""
    guild_id = settings.discord_guild_id
    guild = getattr(user, "guild", None)
    if guild is not None and (not guild_id or guild.id == guild_id):
        return user
    if client is None or not guild_id:
        return None
    guild = client.get_guild(guild_id)
    if guild is None:
        return None
    member = guild.get_member(user.id)
    if member is None:
        try:
            member = await guild.fetch_member(user.id)
        except discord.HTTPException:
            return None
    return member


async def restore_for(interaction) -> None:
    """`restore` pour l'auteur d'une interaction ; ne lève jamais."""
    try:
        member = await member_of(getattr(interaction, "client", None), interaction.user)
        if member is not None:
            await restore(member)
    except Exception:  # noqa: BLE001 — un rôle ne doit jamais casser une réponse
        _logger.exception("parcours : rôles de %s non rendus", interaction.user.id)


async def restore_soon(interaction, wait: float = ROLE_WAIT) -> None:
    """Lance `restore_for` et l'attend au plus `wait` secondes (la réponse
    doit partir à temps ; les rôles suivent si Discord traîne)."""
    task = asyncio.ensure_future(restore_for(interaction))
    _background.add(task)
    task.add_done_callback(_background.discard)
    await asyncio.wait({task}, timeout=wait)


async def reconcile(guild) -> tuple[int, int]:
    """Chaque membre reçoit les rôles de son parcours qui lui manquent.
    Renvoie (rangs donnés, rôles Aventurier donnés)."""
    if not settings.rank_roles:
        return 0, 0
    generation = _generation
    states = await asyncio.to_thread(_states)
    ranks = adventurers = 0
    for member in list(guild.members):
        if generation != _generation:              # parcours remis à zéro entre-temps
            break
        state = states.get(member.id)
        if state is None or member.bot:
            continue
        need_rank, need_adventurer = ap.roles_to_add(
            state.accepted, state.adventurer, has_any_rank_role(member), has_adventurer_role(member))
        if need_rank and await ensure_start_rank_role(member):
            ranks += 1
        if need_adventurer and generation == _generation and await grant_adventurer(member):
            adventurers += 1
    return ranks, adventurers


def journey_role_ids() -> set[int]:
    """Les rôles du parcours : les rangs et Aventurier."""
    ids = set(settings.rank_roles.values())
    if settings.adventurer_role_id:
        ids.add(settings.adventurer_role_id)
    return ids


async def reset_journey(guild) -> tuple[int, list[str]]:
    """Lancement de saison (décision de l'auteur, 09/11/2026) : chaque membre,
    admins compris, perd ses rangs et Aventurier — tout le monde repasse par le
    règlement et le tutoriel. La base doit être vidée AVANT (`reset_season`),
    sinon le rattrapage les redonnerait. Renvoie (membres remis au départ, échecs)."""
    global _generation
    _generation += 1
    journey = journey_role_ids()
    done, failed = 0, []
    for member in list(guild.members):
        held = [role for role in member.roles if role.id in journey]
        if not held or getattr(member, "bot", False):
            continue
        try:
            await member.remove_roles(*held, reason=f"{REASON} — nouvelle saison : retour au règlement")
        except discord.DiscordException as exc:
            failed.append(f"{getattr(member, 'display_name', member.id)} ({exc})")
            continue
        done += 1
    return done, failed


# ------------------------------------------------------------------ salons
def configured() -> bool:
    return bool(settings.adventurer_role_id and settings.rank_roles)


def plan_roles(guild_id: int) -> ap.Roles:
    return ap.Roles(everyone=guild_id, ranks=dict(settings.rank_roles), adventurer=settings.adventurer_role_id)


def audiences() -> dict[int, ap.Audience]:
    return ap.channel_audiences(
        welcome=settings.welcome_channel_id, rules=settings.rules_channel_id,
        tutorial=settings.tutorial_channel_id, tower=settings.tower_channel_id,
        zones=[(z["channel_id"], z.get("rank") or "F") for z in list_zones()])


def _kind(channel) -> str:
    kind = getattr(channel, "type", None)
    if kind == discord.ChannelType.category:
        return "category"
    if kind in (discord.ChannelType.voice, discord.ChannelType.stage_voice):
        return "voice"
    return "text"


def _ordered(channels) -> list:
    """Dans l'ordre du serveur : chaque catégorie, puis ses salons."""
    categories = {c.id: c for c in channels if _kind(c) == "category"}

    def key(channel):
        if _kind(channel) == "category":
            return (channel.position, 0, 0, 0)
        parent = categories.get(getattr(channel, "category_id", None))
        return (parent.position if parent else -1, 1, _kind(channel) == "voice", channel.position)

    return sorted(channels, key=key)


def overwrites_of(channel) -> dict[int, ap.Overwrite]:
    out: dict[int, ap.Overwrite] = {}
    for target, overwrite in channel.overwrites.items():
        allow, deny = overwrite.pair()
        out[target.id] = (allow.value, deny.value)
    return out


def plan(guild_id: int, channels) -> ap.Plan:
    """Ce qu'il faut changer pour que les salons suivent le parcours."""
    roles = plan_roles(guild_id)
    special = audiences()
    result = ap.Plan()
    for channel in _ordered(channels):
        current = overwrites_of(channel)
        audience = special.get(channel.id)
        if audience is None:
            if ap.is_private(current, roles):
                result.private.append(channel.name)
                continue
            audience = ap.ADVENTURERS
        change = ap.plan_channel(channel.id, channel.name, _kind(channel), current, audience, roles)
        if change is not None:
            result.changes.append(change)
    return result


async def apply(guild, channels, changes: list[ap.Change]) -> tuple[int, list[str]]:
    """Applique les changements. Renvoie (salons réglés, échecs)."""
    by_id = {channel.id: channel for channel in channels}
    done, failed = 0, []
    for change in changes:
        channel = by_id.get(change.channel_id)
        if channel is None:
            failed.append(f"{change.title} (salon introuvable)")
            continue
        try:
            for target_id, (allow, deny) in change.updates:
                role = guild.get_role(target_id)
                if role is None:
                    raise LookupError(f"rôle {target_id} introuvable")
                overwrite = None if (allow, deny) == ap.EMPTY else discord.PermissionOverwrite.from_pair(
                    discord.Permissions(allow), discord.Permissions(deny))
                await channel.set_permissions(role, overwrite=overwrite, reason=REASON)
        except (discord.HTTPException, LookupError) as exc:
            failed.append(f"{change.title} ({exc})")
            continue
        done += 1
    return done, failed


async def settle(guild, fetch_channels, *, passes: int = 3) -> tuple[int, list[str]]:
    """Applique le plan, puis le recalcule sur les salons RELUS jusqu'à ce
    qu'il ne reste rien. ⚠️ Modifier une catégorie recopie ses permissions
    dans les salons qui lui sont synchronisés (constaté le 08/11/2026 :
    l'accueil et le tutoriel avaient hérité « aventuriers » de leur
    catégorie, après le calcul du plan). Renvoie (salons réglés, échecs)."""
    touched: set[int] = set()
    for _ in range(passes):
        channels = await fetch_channels()
        changes = plan(guild.id, channels).changes
        if not changes:
            return len(touched), []
        _done, failed = await apply(guild, channels, changes)
        touched.update(change.channel_id for change in changes)
        if failed:                                   # le même refus reviendrait
            return len(touched) - len(failed), failed
    left = plan(guild.id, await fetch_channels()).changes
    return len(touched) - len(left), [f"{change.title} (encore à régler : relance)" for change in left]
