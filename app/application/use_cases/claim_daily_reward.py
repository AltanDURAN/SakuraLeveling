from dataclasses import dataclass
from datetime import datetime, UTC

from app.domain.services.cooldown_service import CooldownService
from app.infrastructure.db.repositories.cooldown_repository import CooldownRepository
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.shared.enums import CooldownAction


@dataclass
class DailyClaimResult:
    success: bool
    streak: int = 0
    gold_gained: int = 0
    next_available_at: datetime | None = None


class ClaimDailyRewardUseCase:
    """Daily reward gold-only avec série persistante.

    Chaque /daily récupéré incrémente la série de 1 et donne `streak × 100` or.
    La série n'est jamais réinitialisée par un jour manqué — elle ne peut que
    grandir (ou être remise à zéro par un admin via /admin reset_player).
    """

    DAILY_ACTION_KEY = CooldownAction.DAILY.value
    GOLD_PER_STREAK = 100

    def __init__(
        self,
        player_repository: PlayerRepository,
        cooldown_repository: CooldownRepository,
        cooldown_service: CooldownService,
    ):
        self.player_repository = player_repository
        self.cooldown_repository = cooldown_repository
        self.cooldown_service = cooldown_service

    def execute(
        self,
        discord_id: int,
        username: str,
        display_name: str,
    ) -> DailyClaimResult:
        profile = self.player_repository.get_or_create_by_discord_id(
            discord_id=discord_id,
            username=username,
            display_name=display_name,
        )

        now = datetime.now(UTC)
        cooldown = self.cooldown_repository.get_by_player_and_action(
            profile.player.id,
            self.DAILY_ACTION_KEY,
        )

        if not self.cooldown_service.is_available(cooldown, now):
            assert cooldown is not None and cooldown.next_available_at is not None
            next_at = cooldown.next_available_at
            if next_at.tzinfo is None:
                next_at = next_at.replace(tzinfo=UTC)
            return DailyClaimResult(
                success=False,
                streak=profile.resources.daily_streak,
                next_available_at=next_at,
            )

        new_streak = self.player_repository.increment_daily_streak(profile.player.id)
        gold_gained = new_streak * self.GOLD_PER_STREAK

        self.player_repository.add_gold(profile.player.id, gold_gained)

        last_used_at, next_available_at = self.cooldown_service.build_next_daily_cooldown(now)
        self.cooldown_repository.upsert(
            player_id=profile.player.id,
            action_key=self.DAILY_ACTION_KEY,
            last_used_at=last_used_at,
            next_available_at=next_available_at,
        )

        return DailyClaimResult(
            success=True,
            streak=new_streak,
            gold_gained=gold_gained,
            next_available_at=next_available_at,
        )
