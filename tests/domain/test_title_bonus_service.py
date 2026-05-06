"""Tests du TitleBonusService (agrégation des effets passifs)."""

from app.domain.entities.title_definition import TitleDefinition
from app.domain.services.title_bonus_service import (
    MAX_BONUS_PCT,
    TitleBonusService,
    TitleBonuses,
)


def _title(code: str, effects: list[dict]) -> TitleDefinition:
    return TitleDefinition(
        code=code,
        name=code.title(),
        description="",
        icon="🏷️",
        condition_type="kills_family",
        condition_target="slime",
        condition_value=100,
        effects=effects,
    )


def test_aggregate_empty_returns_neutral():
    service = TitleBonusService()
    out = service.aggregate([])
    assert out.damage_multiplier_vs("slime") == 1.0
    assert out.damage_received_multiplier_from("slime") == 1.0


def test_single_title_bonus_applied():
    service = TitleBonusService()
    title = _title(
        "slime_slayer",
        [
            {"type": "damage_bonus_vs_family", "target": "slime", "value": 10},
            {"type": "damage_reduction_from_family", "target": "slime", "value": 10},
        ],
    )
    out = service.aggregate([title])
    assert out.damage_multiplier_vs("slime") == 1.10
    assert out.damage_received_multiplier_from("slime") == 0.90


def test_multiple_titles_same_family_stack_additively():
    service = TitleBonusService()
    titles = [
        _title("a", [{"type": "damage_bonus_vs_family", "target": "slime", "value": 10}]),
        _title("b", [{"type": "damage_bonus_vs_family", "target": "slime", "value": 5}]),
    ]
    out = service.aggregate(titles)
    assert out.damage_multiplier_vs("slime") == 1.15


def test_bonus_capped_at_max():
    service = TitleBonusService()
    title = _title(
        "godslayer",
        [{"type": "damage_bonus_vs_family", "target": "slime", "value": 200}],
    )
    out = service.aggregate([title])
    # Bornage à MAX_BONUS_PCT
    assert out.damage_multiplier_vs("slime") == 1.0 + MAX_BONUS_PCT / 100


def test_unknown_effect_type_silently_ignored():
    service = TitleBonusService()
    title = _title(
        "future",
        [{"type": "future_effect_v2", "target": "slime", "value": 50}],
    )
    out = service.aggregate([title])
    assert out.damage_multiplier_vs("slime") == 1.0


def test_bonus_only_applies_to_targeted_family():
    service = TitleBonusService()
    title = _title(
        "slime_only",
        [{"type": "damage_bonus_vs_family", "target": "slime", "value": 20}],
    )
    out = service.aggregate([title])
    assert out.damage_multiplier_vs("slime") == 1.20
    assert out.damage_multiplier_vs("gobelin") == 1.0  # pas affecté


# ---------- Titres exclusifs (Champion 1v1 / Farmer Fou) ----------


def _exclusive_title(code: str, effects: list[dict]) -> TitleDefinition:
    return TitleDefinition(
        code=code, name=code, description="", icon="🏷️",
        condition_type="manual", exclusive=True, effects=effects,
    )


def test_aggregate_champion_all_stats_value():
    service = TitleBonusService()
    title = _exclusive_title("champion_1v1", [{"type": "champion_all_stats", "value": 1}])

    bonuses = service.aggregate([title])

    assert bonuses.champion_all_stats_pct == 1


def test_aggregate_gold_xp_bonus_pct_value():
    service = TitleBonusService()
    title = _exclusive_title("farmer_fou", [{"type": "gold_xp_bonus_pct", "value": 1}])

    bonuses = service.aggregate([title])

    assert bonuses.gold_xp_bonus_pct == 1


def test_apply_to_stats_no_op_when_zero_pct():
    from app.domain.value_objects.stats import Stats

    bonuses = TitleBonuses(champion_all_stats_pct=0)
    stats = Stats(max_hp=100, attack=10, defense=5, crit_chance=5, crit_damage=150,
                  dodge=0, hp_regeneration=2, speed=5)

    assert bonuses.apply_to_stats(stats) == stats


def test_apply_to_stats_one_percent_matches_user_spec():
    """Spec utilisateur : 100 max_hp +1% = 101 ; 11 atk +1% = 12 (ceil) ;
    speed +1 flat ; crit/dodge/crit_dmg +1 additif."""
    from app.domain.value_objects.stats import Stats

    bonuses = TitleBonuses(champion_all_stats_pct=1)
    stats = Stats(
        max_hp=100, attack=11, defense=20,
        crit_chance=5, crit_damage=150, dodge=10,
        hp_regeneration=5, speed=10,
    )

    result = bonuses.apply_to_stats(stats)

    assert result.max_hp == 101  # 100 * 1.01 = 101 exactement
    assert result.attack == 12   # 11 * 1.01 = 11.11 → 12 (ceil)
    assert result.defense == 21  # 20 * 1.01 = 20.2 → 21 (ceil)
    assert result.crit_chance == 6
    assert result.crit_damage == 151
    assert result.dodge == 11
    assert result.speed == 11
    assert result.hp_regeneration == 6


def test_aggregate_multiple_exclusives_stack_pct():
    """Si plusieurs titres au même format coexistent, ils s'additionnent."""
    service = TitleBonusService()
    t1 = _exclusive_title("a", [{"type": "champion_all_stats", "value": 1}])
    t2 = _exclusive_title("b", [{"type": "champion_all_stats", "value": 2}])

    bonuses = service.aggregate([t1, t2])

    assert bonuses.champion_all_stats_pct == 3


# ---------- Bourreau / Intouchable / Chasseur Légendaire / Taverne Addict ----------


def test_bourreau_adds_crit_damage_flat():
    """Bourreau : +5% additif sur crit_damage uniquement."""
    from app.domain.value_objects.stats import Stats

    service = TitleBonusService()
    title = _title("bourreau", [{"type": "crit_damage_flat", "value": 5}])

    bonuses = service.aggregate([title])
    assert bonuses.crit_damage_flat == 5

    stats = Stats(max_hp=100, attack=10, defense=5,
                  crit_chance=5, crit_damage=150, dodge=0,
                  hp_regeneration=0, speed=5)
    out = bonuses.apply_to_stats(stats)

    assert out.crit_damage == 155  # 150 + 5
    # Le reste est inchangé
    assert out.max_hp == 100
    assert out.attack == 10
    assert out.dodge == 0


def test_intouchable_adds_dodge_flat():
    """Intouchable : +1% additif sur dodge."""
    from app.domain.value_objects.stats import Stats

    service = TitleBonusService()
    title = _title("intouchable", [{"type": "dodge_flat", "value": 1}])

    bonuses = service.aggregate([title])
    assert bonuses.dodge_flat == 1

    stats = Stats(max_hp=100, attack=10, defense=5,
                  crit_chance=5, crit_damage=150, dodge=10,
                  hp_regeneration=0, speed=5)
    out = bonuses.apply_to_stats(stats)

    assert out.dodge == 11  # 10 + 1


def test_bourreau_and_intouchable_stack_with_champion():
    """Les flats s'additionnent au bonus Champion 1v1."""
    from app.domain.value_objects.stats import Stats

    bonuses = TitleBonuses(
        champion_all_stats_pct=1,  # +1% global
        crit_damage_flat=5,        # +5 supplémentaire pour Bourreau
        dodge_flat=1,              # +1 supplémentaire pour Intouchable
    )
    stats = Stats(max_hp=100, attack=10, defense=5,
                  crit_chance=5, crit_damage=150, dodge=10,
                  hp_regeneration=5, speed=5)

    out = bonuses.apply_to_stats(stats)

    # crit_damage : champion +1 + bourreau +5 = 156
    assert out.crit_damage == 156
    # dodge : champion +1 + intouchable +1 = 12
    assert out.dodge == 12


def test_chasseur_legendaire_drop_rate_lookup():
    """Drop rate spécifique au mob_code ; autres mobs inchangés."""
    service = TitleBonusService()
    title = _title("chasseur_slime", [
        {"type": "drop_rate_bonus_vs_mob", "target": "slime", "value": 5},
    ])

    bonuses = service.aggregate([title])

    assert bonuses.drop_rate_multiplier_for_mob("slime") == 1.05
    assert bonuses.drop_rate_multiplier_for_mob("gobelin") == 1.0


def test_taverne_addict_collects_daily_bonus_items():
    service = TitleBonusService()
    title = _title("taverne", [
        {"type": "daily_bonus_item", "target": "potion_soin_i", "value": 1},
    ])

    bonuses = service.aggregate([title])

    assert ("potion_soin_i", 1) in bonuses.daily_bonus_items


def test_aggregate_zero_or_missing_target_silently_ignored():
    """Effets mal formés (target vide pour drop_rate) : skip sans crasher."""
    service = TitleBonusService()
    title = _title("oops", [
        {"type": "drop_rate_bonus_vs_mob", "value": 5},  # pas de target
        {"type": "daily_bonus_item", "target": "x", "value": 0},  # qty 0
    ])

    bonuses = service.aggregate([title])

    assert bonuses.drop_rate_bonus_vs_mob == {}
    assert bonuses.daily_bonus_items == []
