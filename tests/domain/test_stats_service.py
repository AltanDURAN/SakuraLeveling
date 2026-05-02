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
    assert stats.hp_regeneration == 5
    assert stats.attack == 10
    assert stats.defense == 5
    assert stats.speed == 5
    assert stats.crit_chance == 5
    assert stats.crit_damage == 150
    assert stats.dodge == 0


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
    assert stats.hp_regeneration == 5
    assert stats.attack == 15
    assert stats.defense == 5
    assert stats.speed == 5


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
    assert stats.hp_regeneration == 5
    assert stats.attack == 13
    assert stats.defense == 7
    assert stats.speed == 5


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
    assert stats.hp_regeneration == 5
    assert stats.attack == 24
    assert stats.defense == 8
    assert stats.speed == 5
    
def test_stats_service_applies_advanced_bonuses():
    profile = build_player_profile(level=1)
    service = StatsService()

    active_class = build_class_definition(
        stat_bonuses={"crit_chance": 10, "dodge": 5}
    )

    sword = build_equipment_item(
        code="hunter_dagger",
        name="Dague du chasseur",
        stat_bonuses={"attack": 4, "crit_chance": 10},
    )

    stats = service.calculate_player_stats(
        profile=profile,
        equipped_items=[sword],
        active_class=active_class,
    )

    assert stats.hp_regeneration == 5
    assert stats.attack == 14
    assert stats.crit_chance == 25
    assert stats.dodge == 5
    assert stats.crit_damage == 150
    assert stats.speed == 5
    
def test_stats_service_applies_hp_regeneration_bonuses():
    profile = build_player_profile(level=1)
    service = StatsService()

    active_class = build_class_definition(
        stat_bonuses={"hp_regeneration": 4}
    )

    item = build_equipment_item(
        code="regen_ring",
        name="Anneau de régénération",
        stat_bonuses={"hp_regeneration": 6},
    )

    stats = service.calculate_player_stats(
        profile=profile,
        equipped_items=[item],
        active_class=active_class,
    )

    assert stats.hp_regeneration == 15

def test_stats_service_applies_speed_bonuses():
    profile = build_player_profile(level=1)
    service = StatsService()

    active_class = build_class_definition(
        stat_bonuses={"speed": 3}
    )

    item = build_equipment_item(
        code="swift_boots",
        name="Bottes rapides",
        stat_bonuses={"speed": 2},
    )

    stats = service.calculate_player_stats(
        profile=profile,
        equipped_items=[item],
        active_class=active_class,
    )

    assert stats.speed == 10


# ---------- Bonus de l'arbre de compétences (skill tree) ----------


def test_stats_service_applies_skill_atk_percent_multiplicatively():
    from app.domain.value_objects.skill_bonuses import SkillBonuses

    profile = build_player_profile(level=1)
    service = StatsService()
    bonuses = SkillBonuses(atk_percent=0.15)  # +15%

    stats = service.calculate_player_stats(
        profile=profile,
        equipped_items=[],
        active_class=None,
        skill_bonuses=bonuses,
    )

    # base atk = 10, +15% = round(10 * 1.15) = 12 (round half to even → 11.5 → 12)
    assert stats.attack == round(10 * 1.15)


def test_stats_service_applies_skill_atk_percent_after_flat_bonuses():
    from app.domain.value_objects.skill_bonuses import SkillBonuses

    profile = build_player_profile(level=1)
    service = StatsService()
    sword = build_equipment_item("sword", "Épée", stat_bonuses={"attack": 10})
    bonuses = SkillBonuses(atk_percent=0.20)  # +20%

    stats = service.calculate_player_stats(
        profile=profile,
        equipped_items=[sword],
        active_class=None,
        skill_bonuses=bonuses,
    )

    # base 10 + équipement 10 = 20, puis ×1.20 = 24
    assert stats.attack == round(20 * 1.20)


def test_stats_service_applies_skill_crit_chance_flat_with_cap():
    from app.domain.value_objects.skill_bonuses import SkillBonuses

    profile = build_player_profile(level=1)
    service = StatsService()
    bonuses = SkillBonuses(crit_chance_flat=80)  # gros boost

    stats = service.calculate_player_stats(
        profile=profile,
        equipped_items=[],
        active_class=None,
        skill_bonuses=bonuses,
    )

    # base crit_chance = 5, +80 = 85, mais cap = 75
    assert stats.crit_chance == 75


def test_stats_service_applies_skill_speed_flat():
    from app.domain.value_objects.skill_bonuses import SkillBonuses

    profile = build_player_profile(level=1)
    service = StatsService()
    bonuses = SkillBonuses(speed_flat=4)

    stats = service.calculate_player_stats(
        profile=profile,
        equipped_items=[],
        active_class=None,
        skill_bonuses=bonuses,
    )

    assert stats.speed == 5 + 4  # base 5 + bonus 4


def test_stats_service_skill_bonuses_none_keeps_legacy_behavior():
    profile = build_player_profile(level=1)
    service = StatsService()

    stats_legacy = service.calculate_player_stats(
        profile=profile,
        equipped_items=[],
        active_class=None,
    )
    stats_with_none = service.calculate_player_stats(
        profile=profile,
        equipped_items=[],
        active_class=None,
        skill_bonuses=None,
    )

    assert stats_legacy == stats_with_none