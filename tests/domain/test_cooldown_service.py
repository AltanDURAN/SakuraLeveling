from datetime import datetime, timedelta, UTC

from app.domain.services.cooldown_service import CooldownService
from app.domain.value_objects.cooldown import Cooldown


def test_cooldown_is_available_when_none():
    service = CooldownService()

    now = datetime.now(UTC)

    assert service.is_available(None, now) is True


def test_cooldown_is_available_when_expired():
    service = CooldownService()

    now = datetime.now(UTC)

    cooldown = Cooldown(
        player_id=1,
        action_key="daily",
        last_used_at=now - timedelta(days=2),
        next_available_at=now - timedelta(hours=1),
    )

    assert service.is_available(cooldown, now) is True


def test_cooldown_is_not_available_when_active():
    service = CooldownService()

    now = datetime.now(UTC)

    cooldown = Cooldown(
        player_id=1,
        action_key="daily",
        last_used_at=now,
        next_available_at=now + timedelta(hours=12),
    )

    assert service.is_available(cooldown, now) is False


def test_build_next_daily_cooldown_resets_at_next_midnight_utc():
    service = CooldownService()

    # 5 mai 2026, 14h30 UTC → next_midnight = 6 mai 2026, 00:00 UTC
    now = datetime(2026, 5, 5, 14, 30, 0, tzinfo=UTC)

    last_used, next_available = service.build_next_daily_cooldown(now)

    assert last_used == now
    assert next_available == datetime(2026, 5, 6, 0, 0, 0, tzinfo=UTC)


def test_build_next_daily_cooldown_just_before_midnight():
    """Réclamer à 23:59:59 UTC autorise la prochaine récup' dès 00:00 (1s plus tard)."""
    service = CooldownService()

    now = datetime(2026, 5, 5, 23, 59, 59, tzinfo=UTC)

    _, next_available = service.build_next_daily_cooldown(now)

    assert next_available == datetime(2026, 5, 6, 0, 0, 0, tzinfo=UTC)
    assert (next_available - now) == timedelta(seconds=1)


def test_build_next_daily_cooldown_just_after_midnight():
    """Réclamer à 00:00:01 UTC fait attendre presque 24h jusqu'au lendemain 00:00."""
    service = CooldownService()

    now = datetime(2026, 5, 5, 0, 0, 1, tzinfo=UTC)

    _, next_available = service.build_next_daily_cooldown(now)

    assert next_available == datetime(2026, 5, 6, 0, 0, 0, tzinfo=UTC)