from dataclasses import dataclass
from datetime import datetime, UTC

from app.application.use_cases.get_skill_tree_state import SKILL_RESET_ACTION_KEY
from app.domain.entities.skill_tree_definition import SkillTreeDefinition
from app.domain.services.cooldown_service import CooldownService
from app.domain.services.skill_tree_service import SkillTreeService
from app.infrastructure.db.repositories.cooldown_repository import CooldownRepository
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.repositories.player_skill_allocation_repository import (
    PlayerSkillAllocationRepository,
)


@dataclass
class ResetSkillTreeResult:
    success: bool
    message: str
    refunded_points: int = 0
    next_reset_available_at: datetime | None = None


class ResetSkillTreeUseCase:
    """Réinitialise complètement l'arbre du joueur, restitue tous ses points
    investis. Cooldown de 7 jours via la table `player_cooldowns` (action_key
    = 'skill_tree_reset').
    """

    COOLDOWN_DAYS = 7

    def __init__(
        self,
        player_repository: PlayerRepository,
        skill_allocation_repository: PlayerSkillAllocationRepository,
        cooldown_repository: CooldownRepository,
        cooldown_service: CooldownService,
        skill_tree_definition: SkillTreeDefinition,
    ) -> None:
        self.player_repository = player_repository
        self.skill_allocation_repository = skill_allocation_repository
        self.cooldown_repository = cooldown_repository
        self.cooldown_service = cooldown_service
        self.skill_tree_service = SkillTreeService(skill_tree_definition)

    def execute(self, discord_id: int) -> ResetSkillTreeResult:
        profile = self.player_repository.get_by_discord_id(discord_id)
        if profile is None:
            return ResetSkillTreeResult(success=False, message="Profil introuvable.")

        now = datetime.now(UTC)
        cooldown = self.cooldown_repository.get_by_player_and_action(
            profile.player.id, SKILL_RESET_ACTION_KEY
        )

        if not self.cooldown_service.is_available(cooldown, now):
            assert cooldown is not None and cooldown.next_available_at is not None
            next_at = cooldown.next_available_at
            if next_at.tzinfo is None:
                next_at = next_at.replace(tzinfo=UTC)
            return ResetSkillTreeResult(
                success=False,
                message=(
                    f"⏳ Reset déjà utilisé. Prochain disponible "
                    f"<t:{int(next_at.timestamp())}:R>."
                ),
                next_reset_available_at=next_at,
            )

        allocations = self.skill_allocation_repository.list_by_player(profile.player.id)
        if not allocations:
            return ResetSkillTreeResult(
                success=False,
                message="ℹ️ Vous n'avez aucun point investi à restituer.",
            )

        refunded = self.skill_tree_service.compute_total_refund(allocations)

        # 1. Vide les allocations
        self.skill_allocation_repository.delete_for_player(profile.player.id)
        # 2. Crédite les points restitués
        self.player_repository.apply_progression(
            player_id=profile.player.id,
            new_level=profile.progression.level,
            new_xp=profile.progression.xp,
            new_skill_points=profile.progression.skill_points + refunded,
        )
        # 3. Pose le cooldown 7 jours
        last_used_at, next_available_at = (
            self.cooldown_service.build_next_skill_reset_cooldown(
                now, days=self.COOLDOWN_DAYS
            )
        )
        self.cooldown_repository.upsert(
            player_id=profile.player.id,
            action_key=SKILL_RESET_ACTION_KEY,
            last_used_at=last_used_at,
            next_available_at=next_available_at,
        )

        return ResetSkillTreeResult(
            success=True,
            message=(
                f"✨ Arbre réinitialisé : **{refunded}** points restitués. "
                f"Prochain reset disponible <t:{int(next_available_at.timestamp())}:R>."
            ),
            refunded_points=refunded,
            next_reset_available_at=next_available_at,
        )
