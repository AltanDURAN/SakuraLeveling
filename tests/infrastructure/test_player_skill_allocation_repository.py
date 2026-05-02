from datetime import datetime, UTC

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.infrastructure.db.base import Base

# Imports nécessaires pour enregistrer toutes les tables dans Base.metadata
from app.infrastructure.db.models.cooldown_model import PlayerCooldownModel  # noqa: F401
from app.infrastructure.db.models.equipment_model import PlayerEquipmentItemModel  # noqa: F401
from app.infrastructure.db.models.inventory_model import PlayerInventoryItemModel  # noqa: F401
from app.infrastructure.db.models.item_model import ItemDefinitionModel  # noqa: F401
from app.infrastructure.db.models.mob_model import MobDefinitionModel  # noqa: F401
from app.infrastructure.db.models.class_model import ClassDefinitionModel  # noqa: F401
from app.infrastructure.db.models.player_class_state_model import PlayerClassStateModel  # noqa: F401
from app.infrastructure.db.models.craft_model import CraftRecipeModel, CraftRecipeIngredientModel  # noqa: F401
from app.infrastructure.db.models.quest_model import QuestDefinitionModel, PlayerQuestStateModel  # noqa: F401
from app.infrastructure.db.models.profession_model import PlayerProfessionModel  # noqa: F401
from app.infrastructure.db.models.player_health_state_model import PlayerHealthStateModel  # noqa: F401
from app.infrastructure.db.models.player_mob_kill_model import PlayerMobKillModel  # noqa: F401
from app.infrastructure.db.models.shop_item_model import ShopItemModel  # noqa: F401
from app.infrastructure.db.models.player_career_stats_model import PlayerCareerStatsModel  # noqa: F401
from app.infrastructure.db.models.player_model import PlayerModel
from app.infrastructure.db.models.progression_model import PlayerProgressionModel  # noqa: F401
from app.infrastructure.db.models.resource_model import PlayerResourceModel  # noqa: F401
from app.infrastructure.db.models.player_skill_allocation_model import PlayerSkillAllocationModel  # noqa: F401

from app.infrastructure.db.repositories.player_skill_allocation_repository import (
    PlayerSkillAllocationRepository,
)


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


def _create_player(session, discord_id: int = 1, name: str = "Alpha") -> int:
    now = datetime.now(UTC)
    player = PlayerModel(
        discord_id=discord_id,
        username=name.lower(),
        display_name=name,
        created_at=now,
        updated_at=now,
        last_seen_at=now,
    )
    session.add(player)
    session.commit()
    return player.id


def test_list_by_player_returns_empty_when_no_allocations(session):
    pid = _create_player(session)
    repo = PlayerSkillAllocationRepository(session)

    assert repo.list_by_player(pid) == {}


def test_upsert_creates_then_updates(session):
    pid = _create_player(session)
    repo = PlayerSkillAllocationRepository(session)

    repo.upsert_level(pid, "force_brute", 1)
    assert repo.list_by_player(pid) == {"force_brute": 1}

    repo.upsert_level(pid, "force_brute", 3)
    assert repo.list_by_player(pid) == {"force_brute": 3}


def test_list_by_player_filters_zero_levels(session):
    pid = _create_player(session)
    repo = PlayerSkillAllocationRepository(session)

    repo.upsert_level(pid, "force_brute", 2)
    repo.upsert_level(pid, "vitalite", 0)  # niveau 0 = ne ressort pas

    result = repo.list_by_player(pid)

    assert result == {"force_brute": 2}


def test_list_by_player_returns_only_target_player(session):
    alpha = _create_player(session, discord_id=1, name="Alpha")
    beta = _create_player(session, discord_id=2, name="Beta")
    repo = PlayerSkillAllocationRepository(session)

    repo.upsert_level(alpha, "force_brute", 2)
    repo.upsert_level(beta, "vitalite", 5)

    assert repo.list_by_player(alpha) == {"force_brute": 2}
    assert repo.list_by_player(beta) == {"vitalite": 5}


def test_delete_for_player_removes_all(session):
    pid = _create_player(session)
    repo = PlayerSkillAllocationRepository(session)

    repo.upsert_level(pid, "force_brute", 3)
    repo.upsert_level(pid, "vitalite", 2)
    repo.delete_for_player(pid)

    assert repo.list_by_player(pid) == {}


def test_delete_for_player_does_not_touch_other_players(session):
    alpha = _create_player(session, discord_id=1, name="Alpha")
    beta = _create_player(session, discord_id=2, name="Beta")
    repo = PlayerSkillAllocationRepository(session)

    repo.upsert_level(alpha, "force_brute", 1)
    repo.upsert_level(beta, "vitalite", 4)
    repo.delete_for_player(alpha)

    assert repo.list_by_player(alpha) == {}
    assert repo.list_by_player(beta) == {"vitalite": 4}
