from dataclasses import dataclass, field
from datetime import datetime

from app.domain.entities.skill_tree_definition import SkillTreeDefinition
from app.domain.services.cooldown_service import CooldownService
from app.domain.services.skill_tree_service import SkillTreeService
from app.infrastructure.db.repositories.cooldown_repository import CooldownRepository
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.repositories.player_skill_allocation_repository import (
    PlayerSkillAllocationRepository,
)


SKILL_RESET_ACTION_KEY = "skill_tree_reset"


@dataclass
class SkillTreeState:
    player_id: int
    discord_id: int
    player_display_name: str
    available_points: int
    spent_points: int
    allocations: dict[str, int] = field(default_factory=dict)
    next_reset_available_at: datetime | None = None


class GetSkillTreeStateUseCase:
    def __init__(
        self,
        player_repository: PlayerRepository,
        skill_allocation_repository: PlayerSkillAllocationRepository,
        cooldown_repository: CooldownRepository,
        skill_tree_definition: SkillTreeDefinition,
    ) -> None:
        self.player_repository = player_repository
        self.skill_allocation_repository = skill_allocation_repository
        self.cooldown_repository = cooldown_repository
        self.skill_tree_service = SkillTreeService(skill_tree_definition)

    def execute(self, discord_id: int) -> SkillTreeState | None:
        profile = self.player_repository.get_by_discord_id(discord_id)
        if profile is None:
            return None

        allocations = self.skill_allocation_repository.list_by_player(profile.player.id)
        spent = self.skill_tree_service.compute_total_refund(allocations)

        cooldown = self.cooldown_repository.get_by_player_and_action(
            profile.player.id, SKILL_RESET_ACTION_KEY
        )
        next_reset_at = cooldown.next_available_at if cooldown is not None else None

        return SkillTreeState(
            player_id=profile.player.id,
            discord_id=profile.player.discord_id,
            player_display_name=profile.player.display_name,
            available_points=profile.progression.skill_points,
            spent_points=spent,
            allocations=allocations,
            next_reset_available_at=next_reset_at,
        )

    def execute_for_self(
        self, discord_id: int, username: str, display_name: str
    ) -> SkillTreeState:
        """Variante qui crée le profil joueur s'il n'existe pas (pour /skill self)."""
        profile = self.player_repository.get_or_create_by_discord_id(
            discord_id=discord_id,
            username=username,
            display_name=display_name,
        )
        allocations = self.skill_allocation_repository.list_by_player(profile.player.id)
        spent = self.skill_tree_service.compute_total_refund(allocations)
        cooldown = self.cooldown_repository.get_by_player_and_action(
            profile.player.id, SKILL_RESET_ACTION_KEY
        )
        return SkillTreeState(
            player_id=profile.player.id,
            discord_id=profile.player.discord_id,
            player_display_name=profile.player.display_name,
            available_points=profile.progression.skill_points,
            spent_points=spent,
            allocations=allocations,
            next_reset_available_at=cooldown.next_available_at if cooldown else None,
        )
