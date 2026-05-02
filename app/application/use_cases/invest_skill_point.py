from dataclasses import dataclass

from app.domain.entities.skill_tree_definition import SkillTreeDefinition
from app.domain.services.skill_tree_service import SkillTreeService
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.repositories.player_skill_allocation_repository import (
    PlayerSkillAllocationRepository,
)


@dataclass
class InvestSkillResult:
    success: bool
    message: str
    skill_code: str = ""
    new_level: int = 0
    cost_paid: int = 0


class InvestSkillPointUseCase:
    """Investit +1 niveau dans une compétence pour un joueur.

    Atomicité : valide puis modifie skill_points et l'allocation dans la même
    transaction (les deux repositories partagent la session SQLAlchemy passée
    par le caller).
    """

    def __init__(
        self,
        player_repository: PlayerRepository,
        skill_allocation_repository: PlayerSkillAllocationRepository,
        skill_tree_definition: SkillTreeDefinition,
    ) -> None:
        self.player_repository = player_repository
        self.skill_allocation_repository = skill_allocation_repository
        self.skill_tree_service = SkillTreeService(skill_tree_definition)
        self.definition = skill_tree_definition

    def execute(self, discord_id: int, skill_code: str) -> InvestSkillResult:
        profile = self.player_repository.get_by_discord_id(discord_id)
        if profile is None:
            return InvestSkillResult(success=False, message="Profil introuvable.")

        allocations = self.skill_allocation_repository.list_by_player(profile.player.id)
        available = profile.progression.skill_points

        ok, message, cost = self.skill_tree_service.validate_investment(
            allocations=allocations,
            available_points=available,
            skill_code=skill_code,
        )
        if not ok:
            return InvestSkillResult(success=False, message=message)

        current_level = allocations.get(skill_code, 0)
        new_level = current_level + 1

        # 1. Décrémente les skill_points
        self.player_repository.apply_progression(
            player_id=profile.player.id,
            new_level=profile.progression.level,
            new_xp=profile.progression.xp,
            new_skill_points=available - cost,
        )
        # 2. Met à jour l'allocation
        self.skill_allocation_repository.upsert_level(
            player_id=profile.player.id,
            skill_code=skill_code,
            level=new_level,
        )

        node = self.definition.get(skill_code)
        node_name = node.name if node else skill_code
        return InvestSkillResult(
            success=True,
            message=(
                f"✨ **{node_name}** investi : niveau **{new_level}**/{node.max_level}"
                if node
                else f"✨ {skill_code} investi : niveau {new_level}"
            ),
            skill_code=skill_code,
            new_level=new_level,
            cost_paid=cost,
        )
