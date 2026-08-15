from app.domain.services.forge_service import ForgeService
from app.domain.services.stats_service import StatsService
from tests.domain.test_stats_service import (
    build_equipment_item,
    build_player_profile,
)


def _attack_with_level(level: int) -> int:
    profile = build_player_profile(level=1)
    item = build_equipment_item("epee", "Épée", {"attack": 10})  # item id=1
    stats = StatsService().calculate_player_stats(
        profile=profile,
        equipped_items=[item],
        active_class=None,
        item_levels={1: level} if level else None,
    )
    return stats.attack


def test_forge_unforged_is_base_plus_item():
    # 10 (base joueur) + 10 (item, ×1) = 20
    assert _attack_with_level(0) == 20


def test_forge_level_1_adds_item_base_once_more():
    # item contribue 10 × (1+1) = 20 → 10 + 20 = 30
    assert _attack_with_level(1) == 30


def test_forge_level_2():
    # item 10 × 3 = 30 → 10 + 30 = 40
    assert _attack_with_level(2) == 40


def test_forge_level_10_cap_value():
    # item 10 × 11 = 110 → 10 + 110 = 120
    assert _attack_with_level(10) == 120


def test_forge_service_cap():
    svc = ForgeService()
    assert svc.is_maxed(10, 10) is True
    assert svc.is_maxed(9, 10) is False


def test_forge_gain_per_level_filters_zero():
    svc = ForgeService()
    assert svc.gain_per_level({"attack": 10, "defense": 0}) == {"attack": 10}
    assert svc.gain_per_level(None) == {}
