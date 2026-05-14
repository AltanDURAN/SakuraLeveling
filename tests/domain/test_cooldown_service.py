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


def test_build_next_daily_cooldown_resets_at_next_paris_midnight_summer():
    """Heure d'été (CEST = UTC+2) : minuit Paris = 22:00 UTC la veille.
    Récup à 14h30 UTC le 5 mai (16h30 Paris) → next = 5 mai 22h UTC
    (= 6 mai 00h00 Paris)."""
    service = CooldownService()

    now = datetime(2026, 5, 5, 14, 30, 0, tzinfo=UTC)

    last_used, next_available = service.build_next_daily_cooldown(now)

    assert last_used == now
    # 6 mai 00:00 Paris (CEST) == 5 mai 22:00 UTC
    assert next_available == datetime(2026, 5, 5, 22, 0, 0, tzinfo=UTC)


def test_build_next_daily_cooldown_resets_at_next_paris_midnight_winter():
    """Heure d'hiver (CET = UTC+1) : minuit Paris = 23:00 UTC la veille."""
    service = CooldownService()

    now = datetime(2026, 1, 10, 14, 30, 0, tzinfo=UTC)

    _, next_available = service.build_next_daily_cooldown(now)

    # 11 janv. 00:00 Paris (CET) == 10 janv. 23:00 UTC
    assert next_available == datetime(2026, 1, 10, 23, 0, 0, tzinfo=UTC)


def test_build_next_daily_cooldown_just_before_paris_midnight():
    """Réclamer à 21:59 UTC (= 23:59 Paris en été) autorise la récup'
    suivante dès 22:00 UTC (= 00:00 Paris), 1 minute plus tard."""
    service = CooldownService()

    now = datetime(2026, 5, 5, 21, 59, 0, tzinfo=UTC)

    _, next_available = service.build_next_daily_cooldown(now)

    assert next_available == datetime(2026, 5, 5, 22, 0, 0, tzinfo=UTC)
    assert (next_available - now) == timedelta(minutes=1)


def test_build_next_daily_cooldown_just_after_paris_midnight():
    """Réclamer à 22:01 UTC (= 00:01 Paris) fait attendre presque 24h
    jusqu'à 22:00 UTC le lendemain (= 00:00 Paris le surlendemain)."""
    service = CooldownService()

    now = datetime(2026, 5, 5, 22, 1, 0, tzinfo=UTC)

    _, next_available = service.build_next_daily_cooldown(now)

    assert next_available == datetime(2026, 5, 6, 22, 0, 0, tzinfo=UTC)