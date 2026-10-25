"""Moteur commun des quêtes quotidiennes et hebdomadaires (quêtes adaptées).

Règles pures dans `app/domain/services/quest_generation_service.py`. Ici :
le PROFIL du joueur (niveau, rôles, familles accessibles), le tirage, la
réclamation et la progression, partagés par `daily_quests` et `weekly_quests`.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy.orm import Session

from app.domain.services import quest_generation_service as qgs
from app.domain.services.progression_service import ProgressionService
from app.domain.services.quest_reward_service import scale_reward

QUESTS_PER_PERIOD = 3


# ------------------------------------------------------------------ profil --
def build_quest_context(session: Session, player_id: int, level: int,
                        rank: str | None = None, family_hint: str | None = None) -> qgs.QuestContext:
    """Profil du joueur pour le tirage. `rank` : rang Discord s'il est connu ;
    sinon `family_hint` (la famille qu'il vient de combattre : sa zone lui est
    donc ouverte) ; sinon seule la zone de base est sûre."""
    from app.domain.services.mob_ability_service import is_group_elite
    from app.domain.services.skill_tree_service import SkillTreeService
    from app.infrastructure.db.repositories.mob_repository import MobRepository
    from app.infrastructure.db.repositories.player_skill_allocation_repository import (
        PlayerSkillAllocationRepository,
    )
    from app.infrastructure.encounters import farm_zone_loader
    from app.infrastructure.skill_tree.skill_tree_loader import get_definition

    allocations = PlayerSkillAllocationRepository(session).list_by_player(player_id)
    classes = SkillTreeService(get_definition()).combat_passives(allocations).classes
    roles = qgs.player_roles(classes)

    if rank is None and family_hint:
        rank = farm_zone_loader.rank_for_family(family_hint)
    accessible = set(farm_zone_loader.families_for_rank(rank))

    mobs = [m for m in MobRepository(session).list_all() if not is_group_elite(m.code)]
    families: list[qgs.FamilyChoice] = []
    for zone in farm_zone_loader.list_zones():
        zone_mobs = [m for m in mobs if m.family in zone["families"]]
        zone_weight = sum(max(0, m.spawn_weight or 0) for m in zone_mobs) or 1
        for family in zone["families"]:
            if family not in accessible:
                continue
            own = [m for m in zone_mobs if m.family == family]
            if not own:
                continue
            levels = [m.xp_reward / qgs.XP_PER_KILL_PER_LEVEL for m in own if m.xp_reward]
            families.append(qgs.FamilyChoice(
                family=family,
                min_level=int(min(levels)) if levels else 1,
                share=sum(max(0, m.spawn_weight or 0) for m in own) / zone_weight,
            ))
    return qgs.QuestContext(level=level, roles=roles, families=tuple(families))


def ensure_assigned(session: Session, repository, templates, player_id: int, period_start: datetime,
                    level: int, rank: str | None = None, family_hint: str | None = None) -> None:
    """Tire les quêtes de la période si le joueur n'en a pas encore."""
    if repository.has_assignments(player_id, period_start):
        return
    ctx = build_quest_context(session, player_id, level, rank, family_hint)
    repository.assign(player_id, period_start, qgs.pick(templates, ctx, QUESTS_PER_PERIOD, random.Random()))


# --------------------------------------------------------------- affichage --
@dataclass
class QuestStatus:
    code: str
    name: str
    description: str
    tier: str
    progress: int
    objective_quantity: int
    completed: bool
    claimed: bool
    reward_gold: int
    reward_xp: int
    reward_items: list


def statuses(assignments, get_definition, level: int) -> list[QuestStatus]:
    out: list[QuestStatus] = []
    for a in assignments:
        template = get_definition(a.quest_code)
        if template is None:
            continue
        out.append(QuestStatus(
            code=a.quest_code, name=a.name or template.name, description=a.description,
            tier=a.tier or template.tier, progress=a.progress,
            objective_quantity=a.objective_quantity, completed=a.completed, claimed=a.claimed,
            reward_gold=scale_reward(template.reward_gold, level),
            reward_xp=scale_reward(template.reward_xp, level),
            reward_items=template.reward_items,
        ))
    return out


# ------------------------------------------------------------- réclamation --
@dataclass
class ClaimedReward:
    quest_code: str
    name: str
    gold: int
    xp: int
    items: list


@dataclass
class ClaimAllResult:
    success: bool
    message: str
    rewards: list[ClaimedReward] = field(default_factory=list)
    leveled_up: bool = False
    new_level: int | None = None


def claim_all(profile, repository, get_definition, period_start: datetime, player_repository,
              item_repository, inventory_repository,
              progression_service: ProgressionService | None = None) -> ClaimAllResult:
    """Réclame d'un coup toutes les quêtes terminées et pas encore réclamées."""
    progression_service = progression_service or ProgressionService()
    claimable = [a for a in repository.list_for_player(profile.player.id, period_start)
                 if a.completed and not a.claimed]
    if not claimable:
        return ClaimAllResult(success=False, message="⚠️ Aucune récompense à récupérer pour l'instant.")

    level = profile.progression.level
    rewards: list[ClaimedReward] = []
    total_xp = 0
    for a in claimable:
        template = get_definition(a.quest_code)
        if template is None:
            continue
        # Montants indexés sur le niveau au moment de la réclamation.
        gold = scale_reward(template.reward_gold, level)
        xp = scale_reward(template.reward_xp, level)
        player_repository.add_gold(profile.player.id, gold)
        total_xp += xp
        for item_code, qty in template.reward_items:
            item = item_repository.get_by_code(item_code)
            if item is not None:
                inventory_repository.add_item(
                    player_id=profile.player.id, item_definition_id=item.id, quantity=int(qty))
        repository.mark_claimed(profile.player.id, period_start, a.quest_code)
        rewards.append(ClaimedReward(a.quest_code, a.name or template.name, gold, xp,
                                     list(template.reward_items)))

    leveled, new_level = False, None
    if total_xp > 0:
        progression = progression_service.apply_level_up(
            current_level=profile.progression.level, current_xp=profile.progression.xp,
            gained_xp=total_xp, current_skill_points=profile.progression.skill_points,
            current_stat_points=profile.progression.stat_points,
        )
        player_repository.apply_progression(
            profile.player.id, progression.level, progression.xp,
            progression.skill_points, progression.stat_points,
        )
        leveled = progression.level > level
        new_level = progression.level if leveled else None
    return ClaimAllResult(success=True, message=f"✅ {len(rewards)} récompense(s) récupérée(s).",
                          rewards=rewards, leveled_up=leveled, new_level=new_level)


# ------------------------------------------------------------ progression --
class QuestProgressService:
    """Hook événementiel — appelé à chaque évènement de jeu pertinent. Renvoie
    les assignations que CET appel vient de terminer (notif côté UI)."""

    #: À définir : période courante et modèles.
    def period_start(self) -> datetime:  # pragma: no cover - abstrait
        raise NotImplementedError

    def templates(self):  # pragma: no cover - abstrait
        raise NotImplementedError

    def __init__(self, quest_repository) -> None:
        self.quest_repository = quest_repository

    def _progress(self, player_id: int, objective_type: str, amount: int,
                  target: str | None = None, family_hint: str | None = None) -> list:
        if amount <= 0:
            return []
        start = self.period_start()
        # Auto-tirage si le joueur n'a pas encore ouvert ses quêtes : sans
        # ça, ses combats ne compteraient pas avant qu'il les consulte.
        if not self.quest_repository.has_assignments(player_id, start):
            from app.infrastructure.db.repositories.player_repository import PlayerRepository

            profile = PlayerRepository(self.quest_repository.session).get_profile_by_player_id(player_id)
            if profile is None:
                return []
            ensure_assigned(self.quest_repository.session, self.quest_repository, self.templates(),
                            player_id, start, profile.progression.level, family_hint=family_hint)
        return self.quest_repository.add_progress_for(player_id, start, objective_type, amount, target)

    def on_kill(self, player_id: int, family: str, mob_code: str = "", count: int = 1,
                group_size: int = 1) -> list:
        out = self._progress(player_id, "kill_any", count, family_hint=family or None)
        if family:
            out += self._progress(player_id, "kill_family", count, target=family)
        if group_size >= 2:
            out += self._progress(player_id, "group_kill", count)
        return out

    def on_daily_claimed(self, player_id: int, count: int = 1) -> list:
        return self._progress(player_id, "daily_claim", count)

    def on_gold_earned(self, player_id: int, amount: int) -> list:
        return self._progress(player_id, "gold_earned", amount)

    def on_xp_earned(self, player_id: int, amount: int) -> list:
        return self._progress(player_id, "xp_earned", amount)

    def on_items_dropped(self, player_id: int, count: int) -> list:
        return self._progress(player_id, "items_dropped", count)

    def on_damage_dealt(self, player_id: int, amount: int) -> list:
        return self._progress(player_id, "damage_dealt", amount)

    def on_damage_tanked(self, player_id: int, amount: int) -> list:
        return self._progress(player_id, "damage_tanked", amount)

    def on_hp_healed(self, player_id: int, amount: int) -> list:
        return self._progress(player_id, "hp_healed", amount)

    def on_role_trial(self, player_id: int, role: str) -> list:
        """Un défi RELEVÉ (premier essai d'un rôle dans la journée)."""
        return self._progress(player_id, "role_trial", 1, target=role)
