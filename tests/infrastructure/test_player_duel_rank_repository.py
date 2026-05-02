"""Tests du PlayerDuelRankRepository (ladder 1v1)."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.infrastructure.db.base import Base

# Imports nécessaires pour Base.metadata
from app.infrastructure.db.models.player_model import PlayerModel
from app.infrastructure.db.models.progression_model import PlayerProgressionModel  # noqa: F401
from app.infrastructure.db.models.resource_model import PlayerResourceModel  # noqa: F401
from app.infrastructure.db.models.item_model import ItemDefinitionModel  # noqa: F401
from app.infrastructure.db.models.inventory_model import PlayerInventoryItemModel  # noqa: F401
from app.infrastructure.db.models.equipment_model import PlayerEquipmentItemModel  # noqa: F401
from app.infrastructure.db.models.mob_model import MobDefinitionModel  # noqa: F401
from app.infrastructure.db.models.class_model import ClassDefinitionModel  # noqa: F401
from app.infrastructure.db.models.player_class_state_model import PlayerClassStateModel  # noqa: F401
from app.infrastructure.db.models.craft_model import CraftRecipeModel, CraftRecipeIngredientModel  # noqa: F401
from app.infrastructure.db.models.cooldown_model import PlayerCooldownModel  # noqa: F401
from app.infrastructure.db.models.quest_model import QuestDefinitionModel, PlayerQuestStateModel  # noqa: F401
from app.infrastructure.db.models.profession_model import PlayerProfessionModel  # noqa: F401
from app.infrastructure.db.models.player_health_state_model import PlayerHealthStateModel  # noqa: F401
from app.infrastructure.db.models.player_mob_kill_model import PlayerMobKillModel  # noqa: F401
from app.infrastructure.db.models.shop_item_model import ShopItemModel  # noqa: F401
from app.infrastructure.db.models.player_career_stats_model import PlayerCareerStatsModel  # noqa: F401
from app.infrastructure.db.models.player_skill_allocation_model import PlayerSkillAllocationModel  # noqa: F401
from app.infrastructure.db.models.trade_model import TradeItemModel, TradeModel  # noqa: F401
from app.infrastructure.db.models.player_duel_rank_model import PlayerDuelRankModel  # noqa: F401

from app.infrastructure.db.repositories.player_duel_rank_repository import (
    PlayerDuelRankRepository,
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


def _create_player(session, discord_id: int, name: str) -> int:
    now = datetime.now(UTC)
    player = PlayerModel(
        discord_id=discord_id, username=name.lower(), display_name=name,
        created_at=now, updated_at=now, last_seen_at=now,
    )
    session.add(player)
    session.commit()
    return player.id


def test_get_or_create_assigns_bottom_position_to_newcomers(session):
    repo = PlayerDuelRankRepository(session)
    p1 = _create_player(session, 1, "Alice")
    p2 = _create_player(session, 2, "Bob")
    p3 = _create_player(session, 3, "Charlie")

    rank1 = repo.get_or_create(p1)
    rank2 = repo.get_or_create(p2)
    rank3 = repo.get_or_create(p3)

    assert rank1.rank_position == 1
    assert rank2.rank_position == 2
    assert rank3.rank_position == 3
    assert rank1.wins == 0
    assert rank1.losses == 0


def test_get_or_create_is_idempotent(session):
    repo = PlayerDuelRankRepository(session)
    p1 = _create_player(session, 1, "Alice")

    first = repo.get_or_create(p1)
    second = repo.get_or_create(p1)

    assert first.rank_position == second.rank_position == 1
    # Une seule ligne en DB
    assert len(repo.list_all()) == 1


def test_swap_positions_exchanges_two_ranks(session):
    repo = PlayerDuelRankRepository(session)
    p1 = _create_player(session, 1, "Alice")
    p2 = _create_player(session, 2, "Bob")

    repo.get_or_create(p1)  # pos 1
    repo.get_or_create(p2)  # pos 2

    repo.swap_positions(p2, p1)  # Bob (#2) bat Alice (#1)

    assert repo.get_by_player_id(p2).rank_position == 1
    assert repo.get_by_player_id(p1).rank_position == 2


def test_increment_wins_and_losses(session):
    repo = PlayerDuelRankRepository(session)
    p1 = _create_player(session, 1, "Alice")
    repo.get_or_create(p1)

    repo.increment_wins(p1)
    repo.increment_wins(p1)
    repo.increment_losses(p1)

    rank = repo.get_by_player_id(p1)
    assert rank.wins == 2
    assert rank.losses == 1


def test_list_top_returns_sorted_ascending_by_rank_position(session):
    repo = PlayerDuelRankRepository(session)
    p1 = _create_player(session, 1, "Alice")
    p2 = _create_player(session, 2, "Bob")
    p3 = _create_player(session, 3, "Charlie")
    repo.get_or_create(p1)
    repo.get_or_create(p2)
    repo.get_or_create(p3)

    # Charlie bat Alice (#1) → Charlie #1, Alice #3
    repo.swap_positions(p3, p1)

    top = repo.list_top(limit=10)
    positions = [r.rank_position for r in top]
    assert positions == [1, 2, 3]
    # Charlie est désormais en #1
    assert top[0].player_id == p3


def test_delete_for_player_removes_row_only_for_that_player(session):
    repo = PlayerDuelRankRepository(session)
    p1 = _create_player(session, 1, "Alice")
    p2 = _create_player(session, 2, "Bob")
    repo.get_or_create(p1)
    repo.get_or_create(p2)

    repo.delete_for_player(p1)

    assert repo.get_by_player_id(p1) is None
    assert repo.get_by_player_id(p2) is not None
