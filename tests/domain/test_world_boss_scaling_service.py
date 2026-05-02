"""Tests du WorldBossScalingService (bonus d'équipe par participants)."""

from app.domain.services.world_boss_scaling_service import WorldBossScalingService
from app.domain.value_objects.stats import Stats


def _stats(**kwargs):
    base = dict(
        max_hp=100, attack=20, defense=10, speed=5,
        crit_chance=0, crit_damage=100, dodge=0, hp_regeneration=0,
    )
    base.update(kwargs)
    return Stats(**base)


def test_solo_participant_gets_no_bonus():
    service = WorldBossScalingService()
    assert service.compute_team_bonus_multiplier(1) == 1.0
    out = service.apply_team_bonus(_stats(), num_participants=1)
    assert out.attack == 20
    assert out.max_hp == 100


def test_two_participants_get_5_percent():
    service = WorldBossScalingService()
    assert service.compute_team_bonus_multiplier(2) == 1.05
    out = service.apply_team_bonus(_stats(attack=100), num_participants=2)
    assert out.attack == 105


def test_bonus_caps_at_50_percent():
    """Au-delà de 11 participants, le bonus reste à +50%."""
    service = WorldBossScalingService()
    # 11 participants = +50% (10 additionnels × 5% = 50%)
    assert service.compute_team_bonus_multiplier(11) == 1.50
    # 50 participants : toujours capé à 1.50
    assert service.compute_team_bonus_multiplier(50) == 1.50


def test_speed_crit_dodge_not_boosted():
    """Seules attack/defense/max_hp sont multipliées."""
    service = WorldBossScalingService()
    base = _stats(speed=10, crit_chance=15, dodge=8, hp_regeneration=3)
    out = service.apply_team_bonus(base, num_participants=10)
    assert out.speed == 10
    assert out.crit_chance == 15
    assert out.dodge == 8
    assert out.hp_regeneration == 3
    # Mais attack/defense/max_hp sont boostés
    assert out.attack > base.attack
