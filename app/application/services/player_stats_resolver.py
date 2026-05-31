"""Helper centralisé pour calculer les Stats finales d'un joueur.

Encapsule la chaîne répétitive `load skill allocations + aggregate skill bonuses
+ resolve title bonuses + resolve set bonuses + StatsService.calculate_player_stats`,
qui était dupliquée dans ~8 call sites (encounter_service, fight_mob, get_leaderboard,
get_player_stats, use_consumable, admin_cog, player_cog, world_boss).

Avant cet helper : oubli systématique de `skill_bonuses` ET/OU `title_bonuses`
dans plusieurs sites → stats sous-évaluées (cf. audit Phase 1, finding B6 :
`/top power` ignorait l'arbre entier).
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.application.services.set_bonus_resolver import resolve_set_bonuses
from app.application.services.title_bonus_resolver import resolve_title_bonuses
from app.domain.entities.class_definition import ClassDefinition
from app.domain.entities.player_equipment_item import PlayerEquipmentItem
from app.domain.entities.player_profile import PlayerProfile
from app.domain.services.skill_tree_service import SkillTreeService
from app.domain.services.stats_service import StatsService
from app.domain.value_objects.stats import Stats
from app.infrastructure.db.repositories.player_skill_allocation_repository import (
    PlayerSkillAllocationRepository,
)
from app.infrastructure.skill_tree.skill_tree_loader import (
    get_definition as get_skill_tree_definition,
)


def resolve_player_stats(
    session: Session,
    profile: PlayerProfile,
    equipped_items: list[PlayerEquipmentItem],
    active_class: ClassDefinition | None,
    *,
    stats_service: StatsService | None = None,
) -> Stats:
    """Calcule les Stats finales d'un joueur, tous bonus appliqués.

    Charge en interne :
      • skill_bonuses : depuis PlayerSkillAllocationRepository + SkillTreeService
      • title_bonuses : depuis PlayerTitleRepository + title_loader
      • set_bonuses   : depuis les items équipés + set_loader

    Puis appelle StatsService.calculate_player_stats avec les 3 bonus.
    """
    player_id = profile.player.id

    allocations = PlayerSkillAllocationRepository(session).list_by_player(player_id)
    skill_bonuses = SkillTreeService(get_skill_tree_definition()).aggregate_bonuses(allocations)

    title_bonuses = resolve_title_bonuses(session, player_id)
    set_bonuses = resolve_set_bonuses(equipped_items)

    svc = stats_service or StatsService()
    return svc.calculate_player_stats(
        profile=profile,
        equipped_items=equipped_items,
        active_class=active_class,
        skill_bonuses=skill_bonuses,
        set_bonuses=set_bonuses,
        title_bonuses=title_bonuses,
    )
