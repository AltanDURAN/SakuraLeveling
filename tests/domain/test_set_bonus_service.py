"""Tests du SetBonusService — paliers 2/4/8/12 et bonus de panoplie."""

from datetime import UTC, datetime

from app.domain.entities.item_definition import ItemDefinition
from app.domain.entities.player_equipment_item import PlayerEquipmentItem
from app.domain.services.set_bonus_service import SetBonusService


_NOW = datetime.now(UTC)


_SAMPLE_DEFS = {
    "iron": {
        "name": "Acier",
        "icon": "🛡️",
        "tiers": [
            {"min_pieces": 2,  "type": "defense_flat", "value": 1},
            {"min_pieces": 4,  "type": "defense_flat", "value": 2},
            {"min_pieces": 8,  "type": "defense_flat", "value": 5},
            {"min_pieces": 12, "type": "defense_flat", "value": 8},
        ],
    },
    "gobelin": {
        "name": "Gobeline",
        "icon": "👹",
        "tiers": [
            {"min_pieces": 2,  "type": "crit_chance_flat", "value": 1},
            {"min_pieces": 4,  "type": "crit_chance_flat", "value": 2},
        ],
    },
}


def _eq(slot: str, code: str, family: str) -> PlayerEquipmentItem:
    item = ItemDefinition(
        id=1, code=code, name=code, description="",
        category="helmet", rarity="common",
        stackable=False, max_stack=None,
        sell_price=1, buy_price=1, icon=None,
        stat_bonuses=None, equipment_slot=slot,
        requires_two_hands=False, family=family,
        created_at=_NOW, updated_at=_NOW,
    )
    return PlayerEquipmentItem(
        id=1, player_id=1, slot=slot, item_definition=item,
        created_at=_NOW, updated_at=_NOW,
    )


def test_no_bonus_below_first_tier():
    service = SetBonusService(_SAMPLE_DEFS)
    equipped = [_eq("casque", "iron_helmet", "iron")]  # 1 seul item

    bonuses = service.aggregate(equipped)

    # Pas de bonus actif, mais panoplie listée pour info
    assert bonuses.defense_flat == 0
    assert len(bonuses.active_sets) == 1
    s = bonuses.active_sets[0]
    assert s.family == "iron"
    assert s.pieces_equipped == 1
    assert s.active_bonus_type is None
    assert s.next_tier_pieces == 2  # palier 1 = 2 pièces


def test_tier_2_active_at_2_pieces():
    service = SetBonusService(_SAMPLE_DEFS)
    equipped = [
        _eq("casque", "iron_helmet", "iron"),
        _eq("plastron", "iron_chest", "iron"),
    ]

    bonuses = service.aggregate(equipped)

    assert bonuses.defense_flat == 1
    s = bonuses.active_sets[0]
    assert s.pieces_equipped == 2
    assert s.active_bonus_value == 1
    assert s.next_tier_pieces == 4


def test_tier_progresses_with_pieces():
    """Vérifie que les paliers 4/8/12 remplacent (pas additionnent)."""
    service = SetBonusService(_SAMPLE_DEFS)
    eqs = [
        _eq(f"slot_{i}", f"iron_{i}", "iron")
        for i in range(7)
    ]

    bonuses = service.aggregate(eqs)

    # 7 pièces → palier 4 atteint, palier 8 pas encore : bonus = 2 (pas 1+2)
    assert bonuses.defense_flat == 2


def test_tier_max_at_12():
    service = SetBonusService(_SAMPLE_DEFS)
    eqs = [_eq(f"slot_{i}", f"iron_{i}", "iron") for i in range(12)]

    bonuses = service.aggregate(eqs)

    assert bonuses.defense_flat == 8
    s = bonuses.active_sets[0]
    assert s.next_tier_pieces is None  # plus de palier au-dessus


def test_multiple_families_stack_independently():
    service = SetBonusService(_SAMPLE_DEFS)
    equipped = [
        _eq("casque", "iron_h", "iron"),
        _eq("plastron", "iron_c", "iron"),
        _eq("bague", "gobelin_r", "gobelin"),
        _eq("collier", "gobelin_n", "gobelin"),
    ]

    bonuses = service.aggregate(equipped)

    # Iron palier 2 = +1 défense
    assert bonuses.defense_flat == 1
    # Gobelin palier 2 = +1 crit
    assert bonuses.crit_chance_flat == 1
    # Deux panoplies actives
    actives_with_bonus = [
        s for s in bonuses.active_sets if s.active_bonus_type
    ]
    assert len(actives_with_bonus) == 2


def test_unknown_family_in_definitions_skipped_silently():
    service = SetBonusService(_SAMPLE_DEFS)
    equipped = [
        _eq("casque", "weird", "unknown_family"),
        _eq("plastron", "weird2", "unknown_family"),
    ]

    bonuses = service.aggregate(equipped)

    # Famille pas dans les définitions → aucun bonus, ni listée
    assert bonuses.defense_flat == 0
    assert bonuses.active_sets == []


def test_item_without_family_ignored():
    service = SetBonusService(_SAMPLE_DEFS)
    equipped = [
        _eq("casque", "no_family", ""),
        _eq("plastron", "iron_c", "iron"),
    ]

    bonuses = service.aggregate(equipped)

    # Le item sans famille n'est pas compté → iron a 1 seul, pas de bonus
    assert bonuses.defense_flat == 0
    iron_set = next(
        (s for s in bonuses.active_sets if s.family == "iron"), None,
    )
    assert iron_set is not None
    assert iron_set.pieces_equipped == 1


def test_higher_tier_replaces_lower():
    """Comportement clé : on prend le PLUS HAUT palier atteint, pas la
    somme cumulative des paliers."""
    service = SetBonusService(_SAMPLE_DEFS)
    eqs = [_eq(f"s{i}", f"i{i}", "iron") for i in range(8)]

    bonuses = service.aggregate(eqs)

    # 8 pièces = palier 8 directement (+5), pas 1+2+5=8
    assert bonuses.defense_flat == 5
