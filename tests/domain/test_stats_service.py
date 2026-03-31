from datetime import datetime, UTC

from app.domain.entities.class_definition import ClassDefinition
from app.domain.entities.item_definition import ItemDefinition
from app.domain.entities.player import Player
from app.domain.entities.player_equipment_item import PlayerEquipmentItem
from app.domain.entities.player_profile import PlayerProfile
from app.domain.entities.player_progression import PlayerProgression
from app.domain.entities.player_resources import PlayerResources
from app.domain.services.stats_service import StatsService


def build_player_profile(level: int = 1) -> PlayerProfile:
    now = datetime.now(UTC)

    player = Player(
        id=1,
        discord_id=123456789,
        username="test_user",
        display_name="TestUser",
        created_at=now,
        updated_at=now,
        last_seen_at=now,
    )

    progression = PlayerProgression(
        player_id=1,
        level=level,
        xp=0,
        skill_points=0,
        created_at=now,
        updated_at=now,
    )

    resources = PlayerResources(
        player_id=1,
        gold=0,
        created_at=now,
        updated_at=now,
    )

    return PlayerProfile(
        player=player,
        progression=progression,
        resources=resources,
    )


def build_equipment_item(
    code: str,
    name: str,
    stat_bonuses: dict | None,
) -> PlayerEquipmentItem:
    now = datetime.now(UTC)

    item_definition = ItemDefinition(
        id=1,
        code=code,
        name=name,
        description="",
        category="weapon",
        rarity="common",
        stackable=False,
        max_stack=None,
        sell_price=0,
        buy_price=None,
        icon=None,
        stat_bonuses=stat_bonuses,
        created_at=now,
        updated_at=now,
    )

    return PlayerEquipmentItem(
        id=1,
        player_id=1,
        slot="weapon",
        item_definition=item_definition,
        created_at=now,
        updated_at=now,
    )


def build_class_definition(stat_bonuses: dict | None) -> ClassDefinition:
    now = datetime.now(UTC)

    return ClassDefinition(
        id=1,
        code="warrior",
        name="Guerrier",
        description="",
        stat_bonuses=stat_bonuses,
        unlock_requirements=None,
        created_at=now,
        updated_at=now,
    )


def test_stats_service_level_1_without_equipment_or_class():
    profile = build_player_profile(level=1)
    service = StatsService()

    stats = service.calculate_player_stats(
        profile=profile,
        equipped_items=[],
        active_class=None,
    )

    assert stats.max_hp == 100
    assert stats.attack == 10
    assert stats.defense == 5
    assert stats.crit_chance == 0.05
    assert stats.crit_damage == 1.50
    assert stats.dodge == 0.00


def test_stats_service_applies_equipment_bonuses():
    profile = build_player_profile(level=1)
    service = StatsService()

    sword = build_equipment_item(
        code="wood_sword",
        name="Épée en bois",
        stat_bonuses={"attack": 5},
    )

    stats = service.calculate_player_stats(
        profile=profile,
        equipped_items=[sword],
        active_class=None,
    )

    assert stats.max_hp == 100
    assert stats.attack == 15
    assert stats.defense == 5


def test_stats_service_applies_class_bonuses():
    profile = build_player_profile(level=1)
    service = StatsService()

    active_class = build_class_definition(
        stat_bonuses={"max_hp": 20, "attack": 3, "defense": 2}
    )

    stats = service.calculate_player_stats(
        profile=profile,
        equipped_items=[],
        active_class=active_class,
    )

    assert stats.max_hp == 120
    assert stats.attack == 13
    assert stats.defense == 7


def test_stats_service_applies_class_and_equipment_bonuses_together():
    profile = build_player_profile(level=2)
    service = StatsService()

    active_class = build_class_definition(
        stat_bonuses={"max_hp": 20, "attack": 3, "defense": 2}
    )

    sword = build_equipment_item(
        code="slime_blade",
        name="Lame visqueuse",
        stat_bonuses={"attack": 9},
    )

    stats = service.calculate_player_stats(
        profile=profile,
        equipped_items=[sword],
        active_class=active_class,
    )

    # Base niveau 2 = hp 110, atk 12, def 6
    # Classe = +20 hp, +3 atk, +2 def
    # Équipement = +9 atk
    assert stats.max_hp == 130
    assert stats.attack == 24
    assert stats.defense == 8
    
def test_stats_service_applies_advanced_bonuses():
    profile = build_player_profile(level=1)
    service = StatsService()

    active_class = build_class_definition(
        stat_bonuses={"crit_chance": 0.10, "dodge": 0.05}
    )

    sword = build_equipment_item(
        code="hunter_dagger",
        name="Dague du chasseur",
        stat_bonuses={"attack": 4, "crit_chance": 0.10},
    )

    stats = service.calculate_player_stats(
        profile=profile,
        equipped_items=[sword],
        active_class=active_class,
    )

    assert stats.attack == 14
    assert stats.crit_chance == 0.25
    assert stats.dodge == 0.05
    assert stats.crit_damage == 1.50