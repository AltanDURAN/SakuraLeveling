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


def with_gear_passives(passives: CombatPassives, equipped_items) -> CombatPassives:
    """Ajoute les passifs d'ÉQUIPEMENT (pièces épiques et plus) à ceux de l'arbre.

    Deux passifs existent déjà sous une autre forme dans l'arbre et s'y
    branchent : Perce-armure s'ajoute à la défense ignorée (Léthal), Ténacité
    active le même drapeau que Tenace — une seule fois par combat."""
    from dataclasses import replace

    from app.domain.services.gear_passives import active_passives

    codes = frozenset(active_passives(equipped_items))
    if not codes:
        return passives
    return replace(
        passives,
        gear=passives.gear | codes,
        armor_penetration_pct=passives.armor_penetration_pct + (15 if "armor_pierce" in codes else 0),
        last_stand=passives.last_stand or "tenacity" in codes,
    )


def resolve_party_passives(
    session: Session, player_ids: list[int],
) -> tuple[dict[int, CombatPassives], dict[int, str]]:
    """(passifs de l'arbre + de l'équipement, tactique) par joueur."""
    from app.infrastructure.db.repositories.equipment_repository import EquipmentRepository

    service = SkillTreeService(get_definition())
    allocation_repo = PlayerSkillAllocationRepository(session)
    equipped = EquipmentRepository(session).list_by_player_ids(list(player_ids))
    passives = {
        pid: with_gear_passives(
            service.combat_passives(allocation_repo.list_by_player(pid)),
            equipped.get(pid, []),
        )
        for pid in player_ids
    }
    tactics = {
        pid: normalize_tactic(tactic)
        for pid, tactic in PlayerRepository(session).get_combat_tactics(player_ids).items()
    }
    return passives, tactics
