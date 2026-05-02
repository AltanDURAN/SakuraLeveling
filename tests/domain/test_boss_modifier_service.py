"""Tests du BossModifierService (immunités, enrage, crit immunity)."""

from app.domain.services.boss_modifier_service import BossModifierService
from app.domain.value_objects.stats import Stats


def _stats(**kwargs):
    base = dict(
        max_hp=100, attack=10, defense=5, speed=5,
        crit_chance=20, crit_damage=150, dodge=0, hp_regeneration=0,
    )
    base.update(kwargs)
    return Stats(**base)


def test_no_modifiers_returns_neutral_adjustments():
    service = BossModifierService()
    adj = service.compute_adjustments(
        modifiers={}, boss_max_hp=1000, boss_current_hp=1000,
        boss_attack=100, player_crit_chance=20,
    )
    assert adj.boss_attack == 100
    assert adj.player_crit_chance == 20
    assert adj.damage_immunity_threshold == 0
    assert adj.enraged is False


def test_enrage_applies_when_hp_below_threshold():
    service = BossModifierService()
    modifiers = {"enrage_below_pct": 30, "enrage_attack_multiplier": 1.5}

    # 50% HP : pas enragé
    adj = service.compute_adjustments(
        modifiers=modifiers, boss_max_hp=1000, boss_current_hp=500,
        boss_attack=100, player_crit_chance=0,
    )
    assert adj.enraged is False
    assert adj.boss_attack == 100

    # 25% HP : enragé
    adj = service.compute_adjustments(
        modifiers=modifiers, boss_max_hp=1000, boss_current_hp=250,
        boss_attack=100, player_crit_chance=0,
    )
    assert adj.enraged is True
    assert adj.boss_attack == 150


def test_crit_immunity_neutralizes_player_crit_chance():
    service = BossModifierService()
    adj = service.compute_adjustments(
        modifiers={"crit_immunity": True}, boss_max_hp=1000, boss_current_hp=1000,
        boss_attack=100, player_crit_chance=50,
    )
    assert adj.player_crit_chance == 0


def test_filter_incoming_damage_below_threshold_returns_zero():
    assert BossModifierService.filter_incoming_damage(damage=4, threshold=5) == 0
    assert BossModifierService.filter_incoming_damage(damage=5, threshold=5) == 5
    assert BossModifierService.filter_incoming_damage(damage=10, threshold=5) == 10


def test_filter_incoming_damage_no_threshold_returns_unchanged():
    assert BossModifierService.filter_incoming_damage(damage=3, threshold=0) == 3


def test_apply_adjustments_to_boss_stats_handles_enrage():
    service = BossModifierService()
    base = _stats(attack=100)
    out = service.apply_adjustments_to_boss_stats(
        modifiers={"enrage_below_pct": 50, "enrage_attack_multiplier": 2.0},
        boss_max_hp=1000, boss_current_hp=400,
        base_stats=base,
    )
    # 40% HP < 50% → enragé → atk × 2
    assert out.attack == 200
    # speed/defense/dodge inchangés
    assert out.speed == base.speed
    assert out.defense == base.defense
    assert out.dodge == base.dodge
