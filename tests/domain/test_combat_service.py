from datetime import timezone, datetime

from app.domain.entities.mob_definition import MobDefinition
from app.domain.services.combat_service import CombatService
from app.domain.value_objects.stats import Stats


def build_mob(
    max_hp: int,
    attack: int,
    defense: int,
    xp_reward: int = 10,
    gold_reward: int = 5,
) -> MobDefinition:
    now = datetime.now(timezone.utc)

    return MobDefinition(
        id=1,
        code="slime",
        name="Slime",
        description="",
        image_name="",
        max_hp=max_hp,
        current_hp=max_hp,
        attack=attack,
        defense=defense,
        xp_reward=xp_reward,
        gold_reward=gold_reward,
        spawn_weight=1,
        loot_table=None,
        created_at=now,
        updated_at=now,
    )


def test_combat_service_player_wins_against_weaker_mob():
    service = CombatService()

    player_stats = Stats(
        max_hp=100,
        attack=10,
        defense=5,
        crit_chance=0.0,
        crit_damage=1.50,
        dodge=0.0,
        hp_regeneration=0,
    )

    mob = build_mob(
        max_hp=30,
        attack=6,
        defense=1,
        xp_reward=10,
        gold_reward=5,
    )

    result = service.fight_player_vs_mob(player_stats, mob)

    assert result.victory is True
    assert result.xp_gained == 10
    assert result.gold_gained == 5
    assert result.player_remaining_hp > 0
    assert result.mob_remaining_hp <= 0


def test_combat_service_player_loses_against_stronger_mob():
    service = CombatService()

    player_stats = Stats(
        max_hp=20,
        attack=5,
        defense=1,
        crit_chance=0.0,
        crit_damage=1.50,
        dodge=0.0,
        hp_regeneration=0,
    )

    mob = build_mob(
        max_hp=100,
        attack=15,
        defense=3,
    )

    result = service.fight_player_vs_mob(player_stats, mob)

    assert result.victory is False
    assert result.xp_gained == 0
    assert result.gold_gained == 0
    assert result.player_remaining_hp <= 0


def test_combat_service_damage_has_minimum_of_one():
    service = CombatService()

    player_stats = Stats(
        max_hp=10,
        attack=1,
        defense=999,
        crit_chance=0.0,
        crit_damage=1.50,
        dodge=0.0,
        hp_regeneration=0,
    )

    mob = build_mob(
        max_hp=3,
        attack=1,
        defense=999,
        xp_reward=1,
        gold_reward=1,
    )

    result = service.fight_player_vs_mob(player_stats, mob)

    assert result.turns >= 1
    assert result.victory is True


def test_combat_service_turn_count_is_consistent():
    service = CombatService()

    player_stats = Stats(
        max_hp=100,
        attack=11,
        defense=5,
        crit_chance=0.0,
        crit_damage=1.50,
        dodge=0.0,
        hp_regeneration=0,
    )

    mob = build_mob(
        max_hp=30,
        attack=6,
        defense=1,
    )

    result = service.fight_player_vs_mob(player_stats, mob)

    assert result.turns == 3