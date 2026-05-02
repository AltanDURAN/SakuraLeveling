from datetime import datetime, timedelta, UTC

from app.domain.services.health_regeneration_service import HealthRegenerationService


def test_no_regeneration_if_already_full_hp():
    service = HealthRegenerationService()

    now = datetime.now(UTC)
    result = service.apply_out_of_combat_regeneration(
        current_hp=100,
        max_hp=100,
        hp_regeneration=10,
        last_updated_at=now - timedelta(minutes=5),
        now=now,
    )

    assert result == 100


def test_regeneration_applies_per_full_minute():
    service = HealthRegenerationService()

    now = datetime.now(UTC)
    result = service.apply_out_of_combat_regeneration(
        current_hp=50,
        max_hp=100,
        hp_regeneration=10,
        last_updated_at=now - timedelta(minutes=3),
        now=now,
    )

    assert result == 80


def test_regeneration_does_not_exceed_max_hp():
    service = HealthRegenerationService()

    now = datetime.now(UTC)
    result = service.apply_out_of_combat_regeneration(
        current_hp=95,
        max_hp=100,
        hp_regeneration=10,
        last_updated_at=now - timedelta(minutes=2),
        now=now,
    )

    assert result == 100


def test_no_regeneration_if_less_than_one_full_minute_elapsed():
    service = HealthRegenerationService()

    now = datetime.now(UTC)
    result = service.apply_out_of_combat_regeneration(
        current_hp=50,
        max_hp=100,
        hp_regeneration=10,
        last_updated_at=now - timedelta(seconds=59),
        now=now,
    )

    assert result == 50


def test_no_regeneration_if_regeneration_stat_is_zero():
    service = HealthRegenerationService()

    now = datetime.now(UTC)
    result = service.apply_out_of_combat_regeneration(
        current_hp=50,
        max_hp=100,
        hp_regeneration=0,
        last_updated_at=now - timedelta(minutes=5),
        now=now,
    )

    assert result == 50


def test_current_hp_is_clamped_if_above_max_hp():
    service = HealthRegenerationService()

    now = datetime.now(UTC)
    result = service.apply_out_of_combat_regeneration(
        current_hp=120,
        max_hp=100,
        hp_regeneration=10,
        last_updated_at=now - timedelta(minutes=5),
        now=now,
    )

    assert result == 100