from datetime import datetime, UTC

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.infrastructure.db.base import Base

from app.infrastructure.db.models.player_model import PlayerModel
from app.infrastructure.db.models.progression_model import PlayerProgressionModel
from app.infrastructure.db.models.resource_model import PlayerResourceModel
from app.infrastructure.db.models.item_model import ItemDefinitionModel
from app.infrastructure.db.models.inventory_model import PlayerInventoryItemModel
from app.infrastructure.db.models.equipment_model import PlayerEquipmentItemModel
from app.infrastructure.db.models.mob_model import MobDefinitionModel
from app.infrastructure.db.models.class_model import ClassDefinitionModel
from app.infrastructure.db.models.player_class_state_model import PlayerClassStateModel
from app.infrastructure.db.models.craft_model import CraftRecipeModel, CraftRecipeIngredientModel
from app.infrastructure.db.models.cooldown_model import PlayerCooldownModel
from app.infrastructure.db.models.quest_model import QuestDefinitionModel, PlayerQuestStateModel
from app.infrastructure.db.models.profession_model import PlayerProfessionModel
from app.infrastructure.db.models.player_health_state_model import PlayerHealthStateModel
from app.infrastructure.db.models.player_mob_kill_model import PlayerMobKillModel  # noqa: F401

from app.infrastructure.db.repositories.player_kill_repository import PlayerKillRepository


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _create_player(session, discord_id: int, display_name: str) -> int:
    now = datetime.now(UTC)
    player = PlayerModel(
        discord_id=discord_id,
        username=display_name.lower(),
        display_name=display_name,
        created_at=now,
        updated_at=now,
        last_seen_at=now,
    )
    session.add(player)
    session.flush()

    progression = PlayerProgressionModel(
        player_id=player.id,
        level=1,
        xp=0,
        skill_points=0,
        created_at=now,
        updated_at=now,
    )
    resources = PlayerResourceModel(
        player_id=player.id,
        gold=0,
        created_at=now,
        updated_at=now,
    )
    session.add_all([progression, resources])
    session.commit()
    return player.id


def _create_mob(session, code: str, family: str, name: str | None = None) -> None:
    now = datetime.now(UTC)
    mob = MobDefinitionModel(
        code=code,
        name=name or code,
        description="",
        image_name=f"{code}.png",
        family=family,
        max_hp=100,
        current_hp=100,
        attack=10,
        defense=5,
        speed=5,
        crit_chance=0,
        crit_damage=100,
        dodge=0,
        hp_regeneration=0,
        xp_reward=10,
        gold_reward=5,
        spawn_weight=1,
        created_at=now,
        updated_at=now,
    )
    session.add(mob)
    session.commit()


def test_increment_creates_row_first_time(session):
    repo = PlayerKillRepository(session)
    player_id = _create_player(session, 1, "Alpha")

    repo.increment(player_id, "slime")

    rows = session.query(PlayerMobKillModel).all()
    assert len(rows) == 1
    assert rows[0].mob_code == "slime"
    assert rows[0].kill_count == 1


def test_increment_adds_to_existing_row(session):
    repo = PlayerKillRepository(session)
    player_id = _create_player(session, 1, "Alpha")

    repo.increment(player_id, "slime")
    repo.increment(player_id, "slime")
    repo.increment(player_id, "slime", amount=3)

    assert repo.get_total_kills(player_id) == 5


def test_get_kills_per_mob_returns_dict(session):
    repo = PlayerKillRepository(session)
    player_id = _create_player(session, 1, "Alpha")
    _create_mob(session, "slime", "slime")
    _create_mob(session, "gobelin", "gobelin")

    repo.increment(player_id, "slime", amount=3)
    repo.increment(player_id, "gobelin", amount=7)

    result = repo.get_kills_per_mob(player_id)

    assert result == {"slime": 3, "gobelin": 7}


def test_get_kills_for_family_aggregates_across_mobs(session):
    repo = PlayerKillRepository(session)
    player_id = _create_player(session, 1, "Alpha")
    _create_mob(session, "gobelin", "gobelin")
    _create_mob(session, "gobelin_runique", "gobelin")
    _create_mob(session, "slime", "slime")

    repo.increment(player_id, "gobelin", amount=5)
    repo.increment(player_id, "gobelin_runique", amount=3)
    repo.increment(player_id, "slime", amount=10)

    assert repo.get_kills_for_family(player_id, "gobelin") == 8
    assert repo.get_kills_for_family(player_id, "slime") == 10


def test_top_total_kills_orders_descending(session):
    repo = PlayerKillRepository(session)
    alpha = _create_player(session, 1, "Alpha")
    beta = _create_player(session, 2, "Beta")
    gamma = _create_player(session, 3, "Gamma")
    _create_mob(session, "slime", "slime")

    repo.increment(alpha, "slime", amount=2)
    repo.increment(beta, "slime", amount=10)
    repo.increment(gamma, "slime", amount=5)

    top = repo.top_total_kills(limit=10)

    assert [row[1] for row in top] == ["Beta", "Gamma", "Alpha"]
    assert [row[2] for row in top] == [10, 5, 2]


def test_top_kills_for_mob_only_counts_target_mob(session):
    repo = PlayerKillRepository(session)
    alpha = _create_player(session, 1, "Alpha")
    beta = _create_player(session, 2, "Beta")
    _create_mob(session, "slime", "slime")
    _create_mob(session, "gobelin", "gobelin")

    repo.increment(alpha, "slime", amount=8)
    repo.increment(alpha, "gobelin", amount=20)
    repo.increment(beta, "slime", amount=3)

    top = repo.top_kills_for_mob("slime", limit=10)

    assert [row[1] for row in top] == ["Alpha", "Beta"]
    assert [row[2] for row in top] == [8, 3]


def test_top_kills_for_family_aggregates_per_player(session):
    repo = PlayerKillRepository(session)
    alpha = _create_player(session, 1, "Alpha")
    beta = _create_player(session, 2, "Beta")
    _create_mob(session, "gobelin", "gobelin")
    _create_mob(session, "gobelin_runique", "gobelin")
    _create_mob(session, "slime", "slime")

    repo.increment(alpha, "gobelin", amount=5)
    repo.increment(alpha, "gobelin_runique", amount=4)
    repo.increment(alpha, "slime", amount=100)
    repo.increment(beta, "gobelin", amount=15)

    top = repo.top_kills_for_family("gobelin", limit=10)

    assert [row[1] for row in top] == ["Beta", "Alpha"]
    assert [row[2] for row in top] == [15, 9]


def test_get_total_kills_returns_zero_when_no_kills(session):
    repo = PlayerKillRepository(session)
    player_id = _create_player(session, 1, "Alpha")

    assert repo.get_total_kills(player_id) == 0
