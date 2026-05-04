"""Tests du HelpSubscriberRepository (système /chad)."""

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
from app.infrastructure.db.models.world_boss_model import WorldBossModel, WorldBossParticipationModel  # noqa: F401
from app.infrastructure.db.models.player_title_model import PlayerTitleModel  # noqa: F401
from app.infrastructure.db.models.weekly_quest_model import WeeklyQuestAssignmentModel  # noqa: F401
from app.infrastructure.db.models.daily_quest_model import DailyQuestAssignmentModel  # noqa: F401
from app.infrastructure.db.models.marketplace_listing_model import MarketplaceListingModel  # noqa: F401
from app.infrastructure.db.models.help_subscriber_model import HelpSubscriberModel  # noqa: F401

from app.infrastructure.db.repositories.help_subscriber_repository import (
    HelpSubscriberRepository,
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
    p = PlayerModel(
        discord_id=discord_id, username=name.lower(), display_name=name,
        created_at=now, updated_at=now, last_seen_at=now,
    )
    session.add(p)
    session.commit()
    return p.id


def test_subscribe_then_check_returns_true(session):
    repo = HelpSubscriberRepository(session)
    pid = _create_player(session, 1, "Alice")

    assert repo.is_subscribed(pid) is False
    assert repo.subscribe(pid) is True
    assert repo.is_subscribed(pid) is True


def test_subscribe_idempotent(session):
    repo = HelpSubscriberRepository(session)
    pid = _create_player(session, 1, "Alice")
    repo.subscribe(pid)
    # 2e fois : déjà inscrit → False
    assert repo.subscribe(pid) is False


def test_unsubscribe_works(session):
    repo = HelpSubscriberRepository(session)
    pid = _create_player(session, 1, "Alice")
    repo.subscribe(pid)
    assert repo.unsubscribe(pid) is True
    assert repo.is_subscribed(pid) is False
    # 2e fois : pas inscrit → False
    assert repo.unsubscribe(pid) is False


def test_list_all_discord_ids_returns_subscribers(session):
    repo = HelpSubscriberRepository(session)
    p1 = _create_player(session, 100, "Alice")
    p2 = _create_player(session, 200, "Bob")
    p3 = _create_player(session, 300, "Charlie")

    repo.subscribe(p1)
    repo.subscribe(p2)
    # p3 n'est pas inscrit

    discord_ids = repo.list_all_discord_ids()
    assert set(discord_ids) == {100, 200}
    # p3 n'apparaît pas
    assert 300 not in discord_ids


def test_list_all_discord_ids_empty_when_none(session):
    repo = HelpSubscriberRepository(session)
    assert repo.list_all_discord_ids() == []
