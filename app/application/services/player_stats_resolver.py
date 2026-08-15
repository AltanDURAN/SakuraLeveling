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
from app.application.services.status_effect_resolver import resolve_status_effects
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
    status_bonuses = resolve_status_effects(session, player_id)

    from app.infrastructure.db.repositories.player_item_level_repository import (
        PlayerItemLevelRepository,
    )
    item_levels = PlayerItemLevelRepository(session).get_levels_for_player(player_id)

    svc = stats_service or StatsService()
    return svc.calculate_player_stats(
        profile=profile,
        equipped_items=equipped_items,
        active_class=active_class,
        skill_bonuses=skill_bonuses,
        set_bonuses=set_bonuses,
        title_bonuses=title_bonuses,
        status_bonuses=status_bonuses,
        item_levels=item_levels,
    )


def resolve_player_stats_bulk(
    session: Session,
    profiles: list[PlayerProfile],
    *,
    stats_service: StatsService | None = None,
) -> dict[int, Stats]:
    """Version EN LOT de `resolve_player_stats` : calcule les Stats de N joueurs
    avec un nombre CONSTANT de requêtes (~6) au lieu de ~6 × N.

    Motivation (audit §5) : `/classement` bouclait sur tous les joueurs en
    appelant `resolve_player_stats` — soit ~1 000 requêtes pour 200 joueurs.
    Le résultat par joueur est identique à l'appel unitaire (garanti par test).
    """
    if not profiles:
        return {}

    from app.infrastructure.db.repositories.player_item_level_repository import (
        PlayerItemLevelRepository,
    )
    from app.infrastructure.db.repositories.class_repository import ClassRepository
    from app.infrastructure.db.repositories.equipment_repository import (
        EquipmentRepository,
    )
    from app.infrastructure.db.repositories.player_status_effect_repository import (
        PlayerStatusEffectRepository,
    )
    from app.infrastructure.db.repositories.player_title_repository import (
        PlayerTitleRepository,
    )
    from app.domain.services.status_effect_service import StatusEffectService
    from app.domain.services.title_bonus_service import TitleBonusService
    from app.infrastructure.titles.title_loader import get_definition as _get_title_def

    ids = [p.player.id for p in profiles]

    # --- 6 requêtes groupées, quel que soit le nombre de joueurs ---
    allocations_by_player = PlayerSkillAllocationRepository(session).list_by_players(ids)
    titles_by_player = PlayerTitleRepository(session).list_codes_for_players(ids)
    status_by_player = PlayerStatusEffectRepository(session).list_active_multipliers_bulk(ids)
    levels_by_player = PlayerItemLevelRepository(session).get_levels_for_players(ids)
    equipment_by_player = EquipmentRepository(session).list_by_player_ids(ids)
    classes_by_player = ClassRepository(session).get_current_classes_for_players(ids)

    skill_service = SkillTreeService(get_skill_tree_definition())
    title_service = TitleBonusService()
    status_service = StatusEffectService()
    svc = stats_service or StatsService()

    out: dict[int, Stats] = {}
    for profile in profiles:
        pid = profile.player.id
        equipped = equipment_by_player.get(pid, [])
        title_defs = [
            d for d in (_get_title_def(c) for c in titles_by_player.get(pid, []))
            if d is not None
        ]
        out[pid] = svc.calculate_player_stats(
            profile=profile,
            equipped_items=equipped,
            active_class=classes_by_player.get(pid),
            skill_bonuses=skill_service.aggregate_bonuses(
                allocations_by_player.get(pid, {})
            ),
            set_bonuses=resolve_set_bonuses(equipped),
            title_bonuses=title_service.aggregate(title_defs),
            status_bonuses=status_service.aggregate(status_by_player.get(pid, [])),
            item_levels=levels_by_player.get(pid, {}),
        )
    return out
