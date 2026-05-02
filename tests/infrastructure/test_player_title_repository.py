"""Tests du PlayerTitleRepository (unlock, set_active, list)."""

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

from app.infrastructure.db.repositories.player_title_repository import (
    PlayerTitleRepository,
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


def _create_player(session, discord_id: int) -> int:
    now = datetime.now(UTC)
    p = PlayerModel(
        discord_id=discord_id, username=f"u{discord_id}", display_name=f"P{discord_id}",
        created_at=now, updated_at=now, last_seen_at=now,
    )
    session.add(p)
    session.commit()
    return p.id


def test_unlock_creates_title_idempotent(session):
    repo = PlayerTitleRepository(session)
    pid = _create_player(session, 1)

    assert repo.unlock(pid, "slime_slayer") is True
    # 2e fois : déjà débloqué, retourne False
    assert repo.unlock(pid, "slime_slayer") is False
    codes = repo.list_codes_for_player(pid)
    assert codes == ["slime_slayer"]


def test_set_active_only_works_if_unlocked(session):
    repo = PlayerTitleRepository(session)
    pid = _create_player(session, 1)

    # Tentative sans débloquer → False
    assert repo.set_active(pid, "slime_slayer") is False

    # Débloquer puis activer → True
    repo.unlock(pid, "slime_slayer")
    assert repo.set_active(pid, "slime_slayer") is True
    assert repo.get_active_title_code(pid) == "slime_slayer"


def test_set_active_replaces_previous(session):
    repo = PlayerTitleRepository(session)
    pid = _create_player(session, 1)
    repo.unlock(pid, "slime_slayer")
    repo.unlock(pid, "gobelin_slayer")

    repo.set_active(pid, "slime_slayer")
    repo.set_active(pid, "gobelin_slayer")

    assert repo.get_active_title_code(pid) == "gobelin_slayer"


def test_set_active_none_clears(session):
    repo = PlayerTitleRepository(session)
    pid = _create_player(session, 1)
    repo.unlock(pid, "slime_slayer")
    repo.set_active(pid, "slime_slayer")

    repo.set_active(pid, None)
    assert repo.get_active_title_code(pid) is None


def test_delete_for_player_clears_titles(session):
    repo = PlayerTitleRepository(session)
    pid = _create_player(session, 1)
    repo.unlock(pid, "slime_slayer")
    repo.unlock(pid, "gobelin_slayer")

    repo.delete_for_player(pid)
    assert repo.list_codes_for_player(pid) == []
