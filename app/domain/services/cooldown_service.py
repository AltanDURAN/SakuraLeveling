from datetime import datetime, timedelta, UTC

from app.domain.value_objects.cooldown import Cooldown


def _normalize(dt: datetime) -> datetime:
    """SQLite ne préserve pas le tzinfo : on assume UTC pour les datetimes
    naïfs ressortis de la DB afin que les comparaisons soient toujours
    cohérentes avec un `now` UTC-aware."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


class CooldownService:
    def is_available(self, cooldown: Cooldown | None, now: datetime) -> bool:
        if cooldown is None or cooldown.next_available_at is None:
            return True

        return _normalize(now) >= _normalize(cooldown.next_available_at)

    def build_next_daily_cooldown(self, now: datetime) -> tuple[datetime, datetime]:
        last_used_at = now
        next_available_at = now + timedelta(days=1)
        return last_used_at, next_available_at