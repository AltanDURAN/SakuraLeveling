"""Notifications privées débloquées par les cases « Confort » de l'arbre.

Deux fonctionnalités (cf. `combat_passives.FEATURES`) :
  • `notify_cooldowns` — un message privé quand un temps de recharge est fini ;
  • `notify_events`    — un message privé quand un événement apparaît.

Un message privé peut échouer (MP fermés, joueur parti du serveur) : on
l'ignore poliment, ça ne doit jamais casser une boucle ni un événement.
"""

from __future__ import annotations

import logging

import discord

from app.domain.services.skill_tree_service import SkillTreeService
from app.infrastructure.db.models.player_model import PlayerModel
from app.infrastructure.db.repositories.player_skill_allocation_repository import (
    PlayerSkillAllocationRepository,
)
from app.infrastructure.skill_tree.skill_tree_loader import get_definition

_logger = logging.getLogger("sakura.notifications")

#: Temps de recharge annoncés (ceux de /cd).
COOLDOWN_LABELS: dict[str, str] = {
    "daily": "🌅 Ta récompense quotidienne (`/daily`) t'attend !",
    "world_boss_fight": "👑 Tu peux de nouveau combattre le world boss.",
    "rank_trial": "🎖️ Tu peux retenter l'épreuve de rang (`/epreuve`).",
    "skill_tree_reset": "🌳 Le reset hebdomadaire de ton arbre est disponible (`/arbre`).",
}


def holders_of(session, feature: str) -> dict[int, int]:
    """{player_id: discord_id} des joueurs qui ont débloqué `feature`."""
    service = SkillTreeService(get_definition())
    nodes = service.nodes_granting_feature(feature)
    if not nodes:
        return {}
    player_ids = PlayerSkillAllocationRepository(session).player_ids_with_levels(
        {node.code: node.max_level for node in nodes}
    )
    if not player_ids:
        return {}
    rows = session.query(PlayerModel.id, PlayerModel.discord_id).filter(
        PlayerModel.id.in_(player_ids)
    ).all()
    return {pid: did for pid, did in rows}


async def send_dm(bot: discord.Client, discord_id: int, content: str) -> bool:
    try:
        user = bot.get_user(discord_id) or await bot.fetch_user(discord_id)
        await user.send(content)
        return True
    except (discord.Forbidden, discord.NotFound, discord.HTTPException) as exc:
        _logger.info("MP impossible vers %s : %s", discord_id, exc)
        return False
