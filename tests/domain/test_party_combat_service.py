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
        family="gobelin",
        max_hp=max_hp,
        current_hp=current_hp,
        attack=attack,
        defense=defense,
        speed=speed,
        crit_chance=0,
        crit_damage=100,
        dodge=0,
        hp_regeneration=0,
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
                crit_chance=0,
                crit_damage=150,
                dodge=0,
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
                crit_chance=0,
                crit_damage=150,
                dodge=0,
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


def test_party_combat_service_tracks_per_player_contributions():
    service = PartyCombatService()

    party = [
        {
            "player_id": 1,
            "user_id": 101,
            "name": "Heavy",
            "avatar_url": "",
            "current_hp": 100,
            "max_hp": 100,
            "stats": Stats(
                max_hp=100,
                attack=50,
                defense=10,
                speed=10,
                crit_chance=0,
                crit_damage=100,
                dodge=0,
                hp_regeneration=0,
            ),
        },
        {
            "player_id": 2,
            "user_id": 102,
            "name": "Light",
            "avatar_url": "",
            "current_hp": 100,
            "max_hp": 100,
            "stats": Stats(
                max_hp=100,
                attack=10,
                defense=10,
                speed=10,
                crit_chance=0,
                crit_damage=100,
                dodge=0,
                hp_regeneration=0,
            ),
        },
    ]

    mob = build_mob(current_hp=200, max_hp=200, attack=10, defense=2, speed=1)

    result = service.fight_party_vs_mob(party=party, mob=mob)

    assert len(result.contributions) == 2
    by_id = {c.player_id: c for c in result.contributions}

    assert by_id[1].name == "Heavy"
    assert by_id[2].name == "Light"
    # Heavy fait beaucoup plus de dégâts que Light grâce à son attaque supérieure
    assert by_id[1].damage_dealt > by_id[2].damage_dealt
    # Au total, les dégâts infligés correspondent (au moins) aux PV initiaux du mob tué
    if result.victory:
        assert by_id[1].damage_dealt + by_id[2].damage_dealt >= 200
    # Personne ne s'est régénéré (hp_regeneration=0)
    assert by_id[1].hp_healed == 0
    assert by_id[2].hp_healed == 0


def test_party_combat_service_does_not_count_regen_as_hp_healed():
    """La régénération passive (hp_regeneration) ne doit PAS incrémenter
    hp_healed. Ce champ est réservé aux soins actifs (futur système de
    classe Soigneur). Sinon, un joueur tanky monopoliserait la part heal."""
    service = PartyCombatService()

    party = [
        {
            "player_id": 1,
            "user_id": 101,
            "name": "Tanky",
            "avatar_url": "",
            "current_hp": 50,
            "max_hp": 100,
            "stats": Stats(
                max_hp=100,
                attack=10,
                defense=5,
                speed=10,
                crit_chance=0,
                crit_damage=100,
                dodge=0,
                hp_regeneration=15,
            ),
        },
    ]

    mob = build_mob(current_hp=50, max_hp=50, attack=5, defense=1, speed=5)

    result = service.fight_party_vs_mob(party=party, mob=mob)

    contribution = result.contributions[0]
    assert contribution.hp_healed == 0


def test_party_combat_service_marks_dead_player_as_not_survived():
    service = PartyCombatService()

    party = [
        {
            "player_id": 1,
            "user_id": 101,
            "name": "Glass",
            "avatar_url": "",
            "current_hp": 5,
            "max_hp": 5,
            "stats": Stats(
                max_hp=5,
                attack=1,
                defense=0,
                speed=1,
                crit_chance=0,
                crit_damage=100,
                dodge=0,
                hp_regeneration=0,
            ),
        },
    ]

    mob = build_mob(current_hp=200, max_hp=200, attack=20, defense=0, speed=20)

    result = service.fight_party_vs_mob(party=party, mob=mob)

    assert result.victory is False
    assert result.contributions[0].survived is False
    assert result.contributions[0].final_hp == 0
    assert result.contributions[0].damage_tanked > 0