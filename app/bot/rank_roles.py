"""Gestion des rôles Discord de RANG (accès aux zones de farm par palier).

Chaque joueur porte UN rôle de rang courant (F → SSS). Tout le monde démarre
au Rang F (attribué automatiquement) ; la progression se gagne en battant le GARDIEN de l'épreuve du rang
suivant (`/epreuve`) ou manuellement via `/admin set_rank`. L'accès aux salons de zone est
géré côté Discord (permissions du salon par rôle) — le bot ne fait qu'attribuer
le bon rôle.

Le bot doit avoir la permission « Gérer les rôles » et être positionné
AU-DESSUS de ces rôles dans la hiérarchie du serveur.
"""

from __future__ import annotations

import logging

import discord

from app.infrastructure.config.settings import settings

_logger = logging.getLogger(__name__)

# Ordre croissant des rangs (du plus bas au plus haut).
RANK_ORDER: list[str] = ["F", "E", "D", "C", "B", "A", "S", "SS", "SSS"]

START_RANK = "F"


def _rank_role_id_set() -> set[int]:
    return set(settings.rank_roles.values())


def has_any_rank_role(member: discord.Member) -> bool:
    ids = _rank_role_id_set()
    return any(r.id in ids for r in member.roles)


async def ensure_start_rank_role(member: discord.Member) -> None:
    """Attribue le rôle Rang F si le membre n'a AUCUN rôle de rang.

    Idempotent et non-régressif : un joueur déjà promu (rang ≥ E) n'est jamais
    rétrogradé. No-op si la feature n'est pas configurée (RANK_ROLE_IDS vide).
    """
    if getattr(member, "bot", False):
        return
    roles = settings.rank_roles
    start_id = roles.get(START_RANK)
    if not start_id:
        return
    if has_any_rank_role(member):
        return
    role = member.guild.get_role(start_id)
    if role is None:
        _logger.warning("Rang F : rôle %s introuvable sur le serveur", start_id)
        return
    try:
        await member.add_roles(role, reason="Début d'aventure — Rang F")
    except discord.DiscordException as exc:
        _logger.warning("Rang F : échec attribution à %s : %s", member.id, exc)


def current_rank(member: discord.Member) -> str:
    """Rang porté par le membre. Le plus HAUT s'il en porte plusieurs (un
    reliquat de manipulation manuelle ne doit pas rétrograder le joueur)."""
    roles = settings.rank_roles
    by_id = {role_id: rank for rank, role_id in roles.items()}
    held = [by_id[r.id] for r in member.roles if r.id in by_id]
    if not held:
        return START_RANK
    return max(held, key=lambda rank: RANK_ORDER.index(rank)
               if rank in RANK_ORDER else -1)


async def set_rank_role(member: discord.Member, rank: str) -> bool:
    """Positionne le membre au `rank` donné : ajoute son rôle et retire les
    autres rôles de rang (un seul rang courant à la fois). Retourne True si OK.
    """
    rank = rank.strip().upper()
    roles = settings.rank_roles
    target_id = roles.get(rank)
    if not target_id:
        return False
    target = member.guild.get_role(target_id)
    if target is None:
        return False
    all_ids = _rank_role_id_set()
    to_remove = [r for r in member.roles if r.id in all_ids and r.id != target_id]
    try:
        if to_remove:
            await member.remove_roles(*to_remove, reason=f"Changement de rang → {rank}")
        if target not in member.roles:
            await member.add_roles(target, reason=f"Rang → {rank}")
    except discord.DiscordException as exc:
        _logger.warning("set_rank_role %s → %s : %s", member.id, rank, exc)
        return False
    return True
