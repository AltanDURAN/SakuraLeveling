"""Passifs de combat et tactique d'un joueur, prêts pour un moteur de combat.

Un seul point d'entrée pour tous les combats (groupe, world boss, épreuves,
duels) : chacun avait sa propre façon de charger l'arbre ; les passifs ne
doivent pas pouvoir être oubliés à un endroit.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.domain.services.combat_passives import CombatPassives, normalize_tactic
from app.domain.services.skill_tree_service import SkillTreeService
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.repositories.player_skill_allocation_repository import (
    PlayerSkillAllocationRepository,
)
from app.infrastructure.skill_tree.skill_tree_loader import get_definition


def resolve_combat_passives(session: Session, player_id: int) -> CombatPassives:
    allocations = PlayerSkillAllocationRepository(session).list_by_player(player_id)
    return SkillTreeService(get_definition()).combat_passives(allocations)


def resolve_party_passives(
    session: Session, player_ids: list[int],
) -> tuple[dict[int, CombatPassives], dict[int, str]]:
    """(passifs, tactique) par joueur, pour un combat de groupe."""
    service = SkillTreeService(get_definition())
    allocation_repo = PlayerSkillAllocationRepository(session)
    passives = {
        pid: service.combat_passives(allocation_repo.list_by_player(pid))
        for pid in player_ids
    }
    tactics = {
        pid: normalize_tactic(tactic)
        for pid, tactic in PlayerRepository(session).get_combat_tactics(player_ids).items()
    }
    return passives, tactics
