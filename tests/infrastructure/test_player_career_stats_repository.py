from datetime import datetime, UTC

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.infrastructure.db.base import Base

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

from app.infrastructure.db.repositories.player_career_stats_repository import (
    PlayerCareerStatsRepository,
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


def test_get_or_create_returns_zeroed_stats_when_absent(session):
    pid = _create_player(session)
    repo = PlayerCareerStatsRepository(session)

    stats = repo.get_or_create(pid)

    assert stats.player_id == pid
    assert stats.gold_earned_total == 0
    assert stats.damage_dealt_total == 0
    assert stats.damage_tanked_total == 0
    assert stats.hp_healed_total == 0
    assert stats.combats_fought == 0
    assert stats.combats_won == 0
    assert stats.combats_lost == 0


def test_get_or_create_is_idempotent(session):
    pid = _create_player(session)
    repo = PlayerCareerStatsRepository(session)

    stats_a = repo.get_or_create(pid)
    stats_b = repo.get_or_create(pid)

    assert stats_a.player_id == stats_b.player_id


def test_add_increments_specified_fields(session):
    pid = _create_player(session)
    repo = PlayerCareerStatsRepository(session)

    repo.add(
        pid,
        gold_earned=150,
        damage_dealt=200,
        damage_tanked=80,
        hp_healed=15,
        combats_fought=1,
        combats_won=1,
    )

    stats = repo.get_or_create(pid)
    assert stats.gold_earned_total == 150
    assert stats.damage_dealt_total == 200
    assert stats.damage_tanked_total == 80
    assert stats.hp_healed_total == 15
    assert stats.combats_fought == 1
    assert stats.combats_won == 1
    assert stats.combats_lost == 0


def test_add_accumulates_over_multiple_calls(session):
    pid = _create_player(session)
    repo = PlayerCareerStatsRepository(session)

    repo.add(pid, gold_earned=100)
    repo.add(pid, gold_earned=50)
    repo.add(pid, damage_dealt=300)
    repo.add(pid, combats_fought=3, combats_won=2, combats_lost=1)

    stats = repo.get_or_create(pid)
    assert stats.gold_earned_total == 150
    assert stats.damage_dealt_total == 300
    assert stats.combats_fought == 3
    assert stats.combats_won == 2
    assert stats.combats_lost == 1


def test_add_creates_row_lazily_on_first_call(session):
    pid = _create_player(session)
    repo = PlayerCareerStatsRepository(session)

    # Pas d'appel à get_or_create avant
    repo.add(pid, gold_earned=50)

    stats = repo.get_or_create(pid)
    assert stats.gold_earned_total == 50


def test_reset_for_player_removes_row(session):
    pid = _create_player(session)
    repo = PlayerCareerStatsRepository(session)

    repo.add(pid, gold_earned=100, combats_fought=5)
    repo.reset_for_player(pid)

    # Après reset, get_or_create recrée une ligne à zéro
    stats = repo.get_or_create(pid)
    assert stats.gold_earned_total == 0
    assert stats.combats_fought == 0


def test_reset_for_unknown_player_is_silent(session):
    repo = PlayerCareerStatsRepository(session)

    repo.reset_for_player(999)  # n'existe pas, ne doit pas planter
