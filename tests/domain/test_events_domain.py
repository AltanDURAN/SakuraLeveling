import random

from app.domain.services.chest_loot_service import ChestLootService
from app.domain.services.status_effect_service import StatusEffectService
from app.domain.value_objects.stats import Stats


def _stats(**kw):
    base = dict(
        max_hp=100, attack=10, defense=5, speed=5, crit_chance=10,
        crit_damage=150, dodge=10, hp_regeneration=5, mana_max=100,
        mana_regeneration=5,
    )
    base.update(kw)
    return Stats(**base)


# ---------- ChestLootService ----------

def test_chest_parse_filters_invalid():
    svc = ChestLootService()
    entries = svc.parse_entries([
        {"kind": "gold", "gold_amount": 50, "weight": 40},
        {"kind": "item", "item_code": "gel_e", "quantity": 3, "weight": 30},
        {"kind": "item", "item_code": "", "quantity": 3, "weight": 10},   # sans code
        {"kind": "gold", "gold_amount": 10, "weight": 0},                  # poids 0
        {"kind": "bogus", "weight": 5},                                    # kind invalide
        {"kind": "nothing", "weight": 25},
    ])
    kinds = sorted(e.kind for e in entries)
    # gel_e(item), gold, nothing, + item sans code conservé (résout en nothing au roll)
    assert kinds == ["gold", "item", "item", "nothing"]


def test_chest_roll_weighted_deterministic():
    svc = ChestLootService()
    entries = svc.parse_entries([
        {"kind": "gold", "gold_amount": 50, "weight": 90},
        {"kind": "item", "item_code": "diamant", "quantity": 1, "weight": 10},
    ])
    rng = random.Random(1234)
    counts = {"gold": 0, "item": 0, "nothing": 0}
    for _ in range(2000):
        res = svc.roll(entries, rng)
        counts[res.kind] += 1
    # ~90/10 attendu, large tolérance
    assert counts["gold"] > counts["item"] * 3
    assert counts["item"] > 50


def test_chest_roll_empty_gives_nothing():
    svc = ChestLootService()
    assert svc.roll([], random.Random(0)).is_nothing


def test_chest_item_without_code_resolves_nothing():
    svc = ChestLootService()
    entries = svc.parse_entries([{"kind": "item", "item_code": "", "quantity": 3, "weight": 5}])
    assert svc.roll(entries, random.Random(0)).is_nothing


def test_chest_scale_gold_by_level():
    from app.domain.services.chest_loot_service import ChestLootResult
    svc = ChestLootService()
    base = ChestLootResult(kind="gold", gold_amount=100)
    # niveau 50, 2%/niv → ×2
    assert svc.scale_for_level(base, 50, 2).gold_amount == 200
    # niveau 100 → ×3
    assert svc.scale_for_level(base, 100, 2).gold_amount == 300
    # pct 0 → inchangé
    assert svc.scale_for_level(base, 100, 0).gold_amount == 100


def test_chest_scale_item_quantity_floored_at_base():
    from app.domain.services.chest_loot_service import ChestLootResult
    svc = ChestLootService()
    base = ChestLootResult(kind="item", item_code="diamant", quantity=1)
    # niveau 100, 2% → ×3 → 3
    assert svc.scale_for_level(base, 100, 2).quantity == 3
    # niveau 1 → ~×1.02 → arrondi 1, jamais sous la base
    assert svc.scale_for_level(base, 1, 2).quantity == 1


def test_chest_scale_nothing_stays_nothing():
    from app.domain.services.chest_loot_service import ChestLootResult
    svc = ChestLootService()
    assert svc.scale_for_level(ChestLootResult(kind="nothing"), 100, 5).is_nothing


# ---------- StatusEffectService ----------

def test_status_aggregate_multiplicative():
    svc = StatusEffectService()
    bonuses = svc.aggregate([1.1, 0.5])
    assert abs(bonuses.all_stats_multiplier - 0.55) < 1e-9


def test_status_aggregate_empty_is_neutral():
    assert StatusEffectService().aggregate([]).all_stats_multiplier == 1.0


def test_status_buff_applies_plus_10():
    bonuses = StatusEffectService().aggregate([1.1])
    out = bonuses.apply_to_stats(_stats(attack=100, defense=50, max_hp=1000))
    assert out.attack == 110
    assert out.defense == 55
    assert out.max_hp == 1100


def test_status_debuff_halves_positive_stats():
    bonuses = StatusEffectService().aggregate([0.5])
    out = bonuses.apply_to_stats(_stats(attack=100, defense=40, max_hp=1000, dodge=20))
    assert out.attack == 50
    assert out.defense == 20
    assert out.max_hp == 500
    assert out.dodge == 10


def test_status_neutral_multiplier_returns_same():
    bonuses = StatusEffectService().aggregate([1.0])
    s = _stats()
    assert bonuses.apply_to_stats(s) is s


def test_status_crit_damage_floored_at_100():
    bonuses = StatusEffectService().aggregate([0.5])
    out = bonuses.apply_to_stats(_stats(crit_damage=150))
    assert out.crit_damage == 100  # 75 clampé à 100 (neutre)
