"""Tests des helpers ajoutés pour les nouvelles commandes /admin.

Couvre les méthodes de repository directement testables :
    - PlayerRepository.add_skill_points / set_skill_points / set_daily_streak
    - PlayerKillRepository.set_kill_count
"""

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
from app.infrastructure.db.models.mob_model import MobDefinitionModel  # noqa: F401
from app.infrastructure.db.models.cooldown_model import PlayerCooldownModel  # noqa: F401
from app.infrastructure.db.models.quest_model import QuestDefinitionModel, PlayerQuestStateModel  # noqa: F401
from app.infrastructure.db.models.profession_model import PlayerProfessionModel  # noqa: F401
from app.infrastructure.db.models.player_health_state_model import PlayerHealthStateModel  # noqa: F401
from app.infrastructure.db.models.player_mob_kill_model import PlayerMobKillModel  # noqa: F401
from app.infrastructure.db.models.shop_item_model import ShopItemModel  # noqa: F401
from app.infrastructure.db.models.player_career_stats_model import PlayerCareerStatsModel  # noqa: F401
from app.infrastructure.db.models.player_skill_allocation_model import PlayerSkillAllocationModel  # noqa: F401
from app.infrastructure.db.models.trade_model import TradeItemModel, TradeModel  # noqa: F401
from app.infrastructure.db.models.role_trial_model import RoleTrialScoreModel  # noqa: F401

from app.infrastructure.db.repositories.player_kill_repository import PlayerKillRepository
from app.infrastructure.db.repositories.player_repository import PlayerRepository


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
    repo = PlayerRepository(session)
    profile = repo.create_player(
        discord_id=discord_id,
        username=name.lower(),
        display_name=name,
    )
    return profile.player.id


def test_add_skill_points_can_be_negative(session):
    pid = _create_player(session, 1, "Alice")
    repo = PlayerRepository(session)
    repo.set_skill_points(pid, 5)
    repo.add_skill_points(pid, -3)
    assert repo.get_by_discord_id(1).progression.skill_points == 2


def test_add_skill_points_clamps_to_zero(session):
    pid = _create_player(session, 1, "Alice")
    repo = PlayerRepository(session)
    repo.set_skill_points(pid, 2)
    repo.add_skill_points(pid, -10)  # tenter de descendre sous 0
    assert repo.get_by_discord_id(1).progression.skill_points == 0


def test_set_daily_streak(session):
    pid = _create_player(session, 1, "Alice")
    repo = PlayerRepository(session)
    repo.set_daily_streak(pid, 30)
    assert repo.get_by_discord_id(1).resources.daily_streak == 30


def test_set_kill_count_creates_or_updates(session):
    pid = _create_player(session, 1, "Alice")
    kill_repo = PlayerKillRepository(session)

    kill_repo.set_kill_count(pid, "slime", 50)
    assert kill_repo.get_kills_per_mob(pid) == {"slime": 50}

    # Update à une nouvelle valeur
    kill_repo.set_kill_count(pid, "slime", 5)
    assert kill_repo.get_kills_per_mob(pid) == {"slime": 5}

    # Set à 0 supprime la ligne
    kill_repo.set_kill_count(pid, "slime", 0)
    assert kill_repo.get_kills_per_mob(pid) == {}
