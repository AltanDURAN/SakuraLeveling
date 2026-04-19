from datetime import datetime, UTC

from app.domain.entities.mob_definition import MobDefinition
from app.domain.services.party_combat_service import PartyCombatService
from app.domain.value_objects.stats import Stats


def build_mob(
    current_hp: int,
    max_hp: int,
    attack: int,
    defense: int,
    speed: int,
) -> MobDefinition:
    now = datetime.now(UTC)

    return MobDefinition(
        id=1,
        code="goblin",
        name="Gobelin",
        description="",
        image_name="gobelin.png",
        max_hp=max_hp,
        current_hp=current_hp,
        attack=attack,
        defense=defense,
        speed=speed,
        xp_reward=10,
        gold_reward=5,
        spawn_weight=1,
        loot_table=None,
        created_at=now,
        updated_at=now,
    )


def test_party_combat_service_returns_turn_snapshots():
    service = PartyCombatService()

    party = [
        {
            "player_id": 1,
            "user_id": 101,
            "name": "Jean-Yves",
            "avatar_url": "https://example.com/avatar1.png",
            "current_hp": 100,
            "max_hp": 100,
            "stats": Stats(
                max_hp=100,
                attack=20,
                defense=5,
                speed=5,
                crit_chance=0.0,
                crit_damage=1.5,
                dodge=0.0,
                hp_regeneration=0,
            ),
        },
        {
            "player_id": 2,
            "user_id": 102,
            "name": "Altan",
            "avatar_url": "https://example.com/avatar2.png",
            "current_hp": 100,
            "max_hp": 100,
            "stats": Stats(
                max_hp=100,
                attack=15,
                defense=4,
                speed=5,
                crit_chance=0.0,
                crit_damage=1.5,
                dodge=0.0,
                hp_regeneration=0,
            ),
        },
    ]

    mob = build_mob(
        current_hp=60,
        max_hp=60,
        attack=8,
        defense=2,
        speed=5,
    )

    result = service.fight_party_vs_mob(
        party=party,
        mob=mob,
    )

    assert result.turns >= 1
    assert len(result.turn_logs) >= 1
    assert result.mob_name == "Gobelin"
    assert result.mob_image_name == "gobelin.png"

    first_turn = result.turn_logs[0]
    assert first_turn.turn_number == 1
    assert len(first_turn.players_state) == 2
    assert first_turn.mob_state["name"] == "Gobelin"
    assert first_turn.mob_state["image_name"] == "gobelin.png"

    for player_state in first_turn.players_state:
        assert "player_id" in player_state
        assert "user_id" in player_state
        assert "name" in player_state
        assert "avatar_url" in player_state
        assert "current_hp" in player_state
        assert "max_hp" in player_state

    assert "current_hp" in first_turn.mob_state
    assert "max_hp" in first_turn.mob_state
    assert "attack" in first_turn.mob_state
    assert "defense" in first_turn.mob_state
    assert "speed" in first_turn.mob_state