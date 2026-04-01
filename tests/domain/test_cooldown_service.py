from datetime import datetime, timedelta, UTC

from app.domain.services.cooldown_service import CooldownService
from app.domain.value_objects.cooldown import Cooldown


def test_cooldown_is_available_when_none():
    service = CooldownService()

    now = datetime.now(timezone.utc)

    assert service.is_available(None, now) is True


def test_cooldown_is_available_when_expired():
    service = CooldownService()

    now = datetime.now(timezone.utc)

    cooldown = Cooldown(
        player_id=1,
        action_key="daily",
        last_used_at=now - timedelta(days=2),
        next_available_at=now - timedelta(hours=1),
    )

    assert service.is_available(cooldown, now) is True


def test_cooldown_is_not_available_when_active():
    service = CooldownService()

    now = datetime.now(timezone.utc)

    cooldown = Cooldown(
        player_id=1,
        action_key="daily",
        last_used_at=now,
        next_available_at=now + timedelta(hours=12),
    )

    assert service.is_available(cooldown, now) is False


def test_build_next_daily_cooldown():
    service = CooldownService()

    now = datetime.now(timezone.utc)

    last_used, next_available = service.build_next_daily_cooldown(now)

    assert last_used == now
    assert next_available == now + timedelta(days=1)