"""Tests des modifiers boss : phases (statiques) + effets dynamiques en combat
(auto-soin, reflet, invocations, seuil d'immunité, cap de tours)."""

from datetime import datetime, UTC

from app.domain.entities.mob_definition import MobDefinition
from app.domain.services.boss_modifier_service import BossModifierService
from app.domain.services.party_combat_service import PartyCombatService
from app.domain.value_objects.stats import Stats


def _mob(hp: int, attack: int, defense: int, max_hp: int | None = None) -> MobDefinition:
    now = datetime.now(UTC)
    return MobDefinition(
        id=1, code="boss", name="Boss", description="", image_name="b.png",
        family="", max_hp=max_hp or hp, current_hp=hp, attack=attack, defense=defense,
        speed=5, crit_chance=0, crit_damage=100, dodge=0, hp_regeneration=0,
        xp_reward=10, gold_reward=5, spawn_weight=1, loot_table=None,
        created_at=now, updated_at=now,
    )


def _party(attack: int = 100, max_hp: int = 100000, defense: int = 10):
    return [{
        "player_id": 1, "user_id": 101, "name": "Hero", "avatar_url": "x",
        "current_hp": max_hp, "max_hp": max_hp,
        "stats": Stats(max_hp=max_hp, attack=attack, defense=defense, speed=5,
                       crit_chance=0, crit_damage=100, dodge=0, hp_regeneration=0),
    }]


# ---------- phases (statiques, BossModifierService) ----------

def test_phases_apply_deepest_multiplier_at_low_hp():
    svc = BossModifierService()
    mods = {"phases": [
        {"below_pct": 50, "attack_multiplier": 1.3},
        {"below_pct": 20, "attack_multiplier": 1.6},
    ]}
    adj = svc.compute_adjustments(
        modifiers=mods, boss_max_hp=1000, boss_current_hp=150,  # 15% → 2 phases
        boss_attack=100, player_crit_chance=0,
    )
    assert adj.boss_attack == 160  # 100 × 1.6 (la plus forte)
    assert adj.enraged is True


def test_phases_inactive_at_high_hp():
    svc = BossModifierService()
    mods = {"phases": [{"below_pct": 50, "attack_multiplier": 1.3}]}
    adj = svc.compute_adjustments(
        modifiers=mods, boss_max_hp=1000, boss_current_hp=900,
        boss_attack=100, player_crit_chance=0,
    )
    assert adj.boss_attack == 100


def test_enrage_and_phase_stack():
    svc = BossModifierService()
    mods = {
        "enrage_below_pct": 30, "enrage_attack_multiplier": 1.5,
        "phases": [{"below_pct": 30, "attack_multiplier": 2.0}],
    }
    adj = svc.compute_adjustments(
        modifiers=mods, boss_max_hp=1000, boss_current_hp=100,
        boss_attack=100, player_crit_chance=0,
    )
    assert adj.boss_attack == 300  # 100 × 1.5 (enrage) × 2.0 (phase)


# ---------- effets dynamiques en combat ----------

def test_immunity_threshold_ignores_weak_hits():
    svc = PartyCombatService()
    # joueur tape 90 net ; seuil 100 → coup ignoré, le boss ne perd rien.
    res = svc.fight_party_vs_mob(
        _party(attack=100), _mob(10_000_000, 1, 10),
        damage_immunity_threshold=100, max_turns=50,
    )
    assert res.contributions[0].damage_dealt == 0


def test_reflect_damages_the_attacker():
    svc = PartyCombatService()
    res = svc.fight_party_vs_mob(
        _party(attack=100, max_hp=100000), _mob(5000, 1, 10),
        boss_reflect_pct=50, max_turns=500,
    )
    # le joueur a encaissé du renvoi → pas à PV pleins
    assert res.contributions[0].final_hp < 100000


def test_auto_heal_with_turn_cap_terminates():
    svc = PartyCombatService()
    # auto-soin énorme > DPS → le boss ne meurt jamais ; le cap arrête le combat.
    res = svc.fight_party_vs_mob(
        _party(attack=50), _mob(10_000, 10, 10, max_hp=10_000),
        boss_heal_per_turn=100_000, max_turns=100,
    )
    assert res.victory is False
    assert res.mob_remaining_hp > 0


def test_adds_deal_extra_damage():
    svc = PartyCombatService()
    adds = {"attack": 200, "summon_turn_interval": 1, "max_active": 3}
    res_adds = svc.fight_party_vs_mob(
        _party(attack=40, max_hp=100000), _mob(600, 50, 10),
        boss_adds=adds, max_turns=500,
    )
    res_none = svc.fight_party_vs_mob(
        _party(attack=40, max_hp=100000), _mob(600, 50, 10), max_turns=500,
    )
    assert res_adds.contributions[0].final_hp < res_none.contributions[0].final_hp
