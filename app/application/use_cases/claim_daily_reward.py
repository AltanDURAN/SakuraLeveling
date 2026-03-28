from datetime import datetime

from app.domain.services.cooldown_service import CooldownService
from app.domain.services.progression_service import ProgressionService
from app.infrastructure.db.repositories.cooldown_repository import CooldownRepository
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.shared.enums import CooldownAction


class ClaimDailyRewardUseCase:
    DAILY_ACTION_KEY = CooldownAction.DAILY.value
    DAILY_GOLD_REWARD = 25
    DAILY_XP_REWARD = 10

    def __init__(
        self,
        player_repository: PlayerRepository,
        cooldown_repository: CooldownRepository,
        cooldown_service: CooldownService,
        progression_service: ProgressionService,
    ):
        self.player_repository = player_repository
        self.cooldown_repository = cooldown_repository
        self.cooldown_service = cooldown_service
        self.progression_service = progression_service

    def execute(
        self,
        discord_id: int,
        username: str,
        display_name: str,
    ) -> tuple[bool, str]:
        profile = self.player_repository.get_or_create_by_discord_id(
            discord_id=discord_id,
            username=username,
            display_name=display_name,
        )

        now = datetime.utcnow()
        cooldown = self.cooldown_repository.get_by_player_and_action(
            profile.player.id,
            self.DAILY_ACTION_KEY,
        )

        if not self.cooldown_service.is_available(cooldown, now):
            assert cooldown is not None and cooldown.next_available_at is not None
            return False, f"Daily déjà récupéré. Prochain disponible : {cooldown.next_available_at} UTC"

        self.player_repository.add_gold(profile.player.id, self.DAILY_GOLD_REWARD)

        new_level, new_xp, new_skill_points = self.progression_service.apply_level_up(
            current_level=profile.progression.level,
            current_xp=profile.progression.xp,
            gained_xp=self.DAILY_XP_REWARD,
            current_skill_points=profile.progression.skill_points,
        )

        self.player_repository.apply_progression(
            player_id=profile.player.id,
            new_level=new_level,
            new_xp=new_xp,
            new_skill_points=new_skill_points,
        )

        last_used_at, next_available_at = self.cooldown_service.build_next_daily_cooldown(now)
        self.cooldown_repository.upsert(
            player_id=profile.player.id,
            action_key=self.DAILY_ACTION_KEY,
            last_used_at=last_used_at,
            next_available_at=next_available_at,
        )

        leveled_up = new_level > profile.progression.level

        message = (
            f"🎁 Daily récupéré : +{self.DAILY_GOLD_REWARD} gold, +{self.DAILY_XP_REWARD} XP"
        )
        if leveled_up:
            message += f"\n🎉 Vous êtes passé niveau {new_level} !"

        return True, message