from dataclasses import dataclass, field
from datetime import datetime, UTC

from app.domain.services.cooldown_service import CooldownService
from app.infrastructure.db.repositories.cooldown_repository import CooldownRepository
from app.infrastructure.db.repositories.inventory_repository import InventoryRepository
from app.infrastructure.db.repositories.item_repository import ItemRepository
from app.infrastructure.db.repositories.player_career_stats_repository import (
    PlayerCareerStatsRepository,
)
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.shared.enums import CooldownAction


@dataclass
class DailyClaimResult:
    success: bool
    streak: int = 0
    gold_gained: int = 0
    next_available_at: datetime | None = None
    # Items octroyés en plus de l'or par les titres (Taverne Addict, etc.).
    # Liste de tuples (item_name, quantity) pour affichage humain.
    bonus_items: list[tuple[str, int]] = field(default_factory=list)
    # Série avant l'absence (si des jours ont été manqués), pour l'annoncer.
    streak_before_absence: int = 0
    days_missed: int = 0
    streak_bonus_pct: int = 0
    # Titres de série débloqués par CE daily (7, 30, 100 jours…).
    titles_unlocked: list[str] = field(default_factory=list)


class ClaimDailyRewardUseCase:
    """Récompense quotidienne : or indexé sur le niveau + bonus de série.

    Règles (cf. `daily_reward_service`) : 20 × niveau, +3 % par jour de série
    (plafond +90 % à 30 jours) ; chaque jour manqué divise la série par deux.
    """

    DAILY_ACTION_KEY = CooldownAction.DAILY.value

    def __init__(
        self,
        player_repository: PlayerRepository,
        cooldown_repository: CooldownRepository,
        cooldown_service: CooldownService,
        career_stats_repository: PlayerCareerStatsRepository | None = None,
    ):
        self.player_repository = player_repository
        self.cooldown_repository = cooldown_repository
        self.cooldown_service = cooldown_service
        self.career_stats_repository = career_stats_repository

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

        from app.domain.services.daily_reward_service import (
            daily_gold,
            missed_days,
            streak_after_absence,
            streak_bonus_pct,
        )

        previous_streak = profile.resources.daily_streak
        missed = missed_days(cooldown.next_available_at if cooldown else None, now)
        kept = streak_after_absence(previous_streak, missed)
        new_streak = kept + 1
        self.player_repository.set_daily_streak(profile.player.id, new_streak)
        gold_gained = daily_gold(profile.progression.level, new_streak)

        self.player_repository.add_gold(profile.player.id, gold_gained)

        if self.career_stats_repository is not None and gold_gained > 0:
            self.career_stats_repository.add(
                profile.player.id, gold_earned=gold_gained
            )

        # Hook titre Taverne Addict : check_daily_streak puis application
        # des bonus daily_bonus_item au prochain claim. Best effort — si
        # n'importe quoi casse, on garde au moins l'or.
        bonus_items: list[tuple[str, int]] = []
        titles_unlocked: list[str] = []
        try:
            session = self.cooldown_repository.session
            from app.application.services.title_bonus_resolver import (
                resolve_title_bonuses,
            )
            from app.application.services.title_unlock_service import (
                TitleUnlockService,
            )
            from app.infrastructure.db.repositories.player_kill_repository import (
                PlayerKillRepository,
            )
            from app.infrastructure.db.repositories.player_title_repository import (
                PlayerTitleRepository,
            )

            # Étape 1 : éventuellement débloquer le titre selon le streak
            events = TitleUnlockService(
                PlayerTitleRepository(session),
                PlayerKillRepository(session),
            ).check_daily_streak(profile.player.id, new_streak)
            titles_unlocked = [f"{e.title.icon} {e.title.name}" for e in events]

            # Étape 2 : appliquer les bonus daily_bonus_item des titres
            # actuellement débloqués (incluant celui qu'on vient peut-être
            # d'octroyer juste au-dessus).
            title_bonuses = resolve_title_bonuses(session, profile.player.id)
            if title_bonuses.daily_bonus_items:
                inventory_repo = InventoryRepository(session)
                item_repo = ItemRepository(session)
                for item_code, qty in title_bonuses.daily_bonus_items:
                    item = item_repo.get_by_code(item_code)
                    if item is None or qty <= 0:
                        continue
                    inventory_repo.add_item(
                        player_id=profile.player.id,
                        item_definition_id=item.id,
                        quantity=qty,
                    )
                    bonus_items.append((item.name, qty))
        except Exception as _e:
            import logging
            logging.getLogger(__name__).warning(
                "Daily title bonus hook failed: %s", _e, exc_info=True,
            )

        last_used_at, next_available_at = self.cooldown_service.build_next_daily_cooldown(now)
        self.cooldown_repository.upsert(
            player_id=profile.player.id,
            action_key=self.DAILY_ACTION_KEY,
            last_used_at=last_used_at,
            next_available_at=next_available_at,
        )

        # Quêtes V2 : on_daily_claimed (compte +1 par claim, daily ET weekly)
        try:
            from app.application.use_cases.weekly_quests import (
                WeeklyQuestProgressService,
            )
            from app.application.use_cases.daily_quests import (
                DailyQuestProgressService,
            )
            from app.infrastructure.db.repositories.weekly_quest_repository import (
                WeeklyQuestRepository,
            )
            from app.infrastructure.db.repositories.daily_quest_repository import (
                DailyQuestRepository,
            )
            session = self.cooldown_repository.session
            WeeklyQuestProgressService(WeeklyQuestRepository(session)).on_daily_claimed(
                profile.player.id,
            )
            DailyQuestProgressService(DailyQuestRepository(session)).on_daily_claimed(
                profile.player.id,
            )
        except Exception as _e:
            import logging
            logging.getLogger(__name__).warning(
                "Quest progress hook failed: %s", _e, exc_info=True,
            )

        return DailyClaimResult(
            success=True,
            streak=new_streak,
            gold_gained=gold_gained,
            next_available_at=next_available_at,
            bonus_items=bonus_items,
            streak_before_absence=previous_streak if missed else 0,
            days_missed=missed,
            streak_bonus_pct=streak_bonus_pct(new_streak),
            titles_unlocked=titles_unlocked,
        )
