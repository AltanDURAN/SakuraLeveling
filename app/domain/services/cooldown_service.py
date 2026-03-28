from datetime import datetime, timedelta

from app.domain.value_objects.cooldown import Cooldown


class CooldownService:
    def is_available(self, cooldown: Cooldown | None, now: datetime) -> bool:
        if cooldown is None or cooldown.next_available_at is None:
            return True

        return now >= cooldown.next_available_at

    def build_next_daily_cooldown(self, now: datetime) -> tuple[datetime, datetime]:
        last_used_at = now
        next_available_at = now + timedelta(days=1)
        return last_used_at, next_available_at