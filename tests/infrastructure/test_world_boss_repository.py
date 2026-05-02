"""Tests du WorldBossRepository."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.domain.entities.world_boss import WorldBossStatus
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

from app.infrastructure.db.repositories.world_boss_repository import WorldBossRepository


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


def test_create_and_get_active(session):
    repo = WorldBossRepository(session)
    boss = repo.create(
        code="boss_test", name="Boss test", image_name="",
        max_hp=10000, attack=100, defense=50, speed=10,
    )
    assert boss.current_hp == 10000
    assert boss.status == WorldBossStatus.ACTIVE

    fetched = repo.get_active()
    assert fetched is not None
    assert fetched.id == boss.id


def test_apply_damage_reduces_hp(session):
    repo = WorldBossRepository(session)
    boss = repo.create(
        code="b", name="B", image_name="", max_hp=1000, attack=10, defense=5, speed=5,
    )
    remaining = repo.apply_damage(boss.id, 300)
    assert remaining == 700
    remaining = repo.apply_damage(boss.id, 1000)  # over-damage
    assert remaining == 0


def test_mark_defeated_changes_status(session):
    repo = WorldBossRepository(session)
    boss = repo.create(
        code="b", name="B", image_name="", max_hp=100, attack=10, defense=5, speed=5,
    )
    repo.mark_defeated(boss.id)

    fetched = repo.get_active()
    assert fetched is None  # plus de boss actif

    by_id = repo.get_by_id(boss.id)
    assert by_id.status == WorldBossStatus.DEFEATED
    assert by_id.defeated_at is not None


def test_upsert_participation_idempotent(session):
    repo = WorldBossRepository(session)
    boss = repo.create(
        code="b", name="B", image_name="", max_hp=100, attack=10, defense=5, speed=5,
    )
    p1 = _create_player(session, 1, "Alice")

    repo.upsert_participation(boss.id, p1, joined=True)
    repo.upsert_participation(boss.id, p1, joined=True)

    parts = repo.list_joined_participants(boss.id)
    assert len(parts) == 1


def test_count_joined_excludes_left_players(session):
    repo = WorldBossRepository(session)
    boss = repo.create(
        code="b", name="B", image_name="", max_hp=100, attack=10, defense=5, speed=5,
    )
    p1 = _create_player(session, 1, "Alice")
    p2 = _create_player(session, 2, "Bob")
    repo.upsert_participation(boss.id, p1, joined=True)
    repo.upsert_participation(boss.id, p2, joined=True)
    repo.upsert_participation(boss.id, p2, joined=False)  # Bob quitte

    assert repo.count_joined(boss.id) == 1


def test_add_combat_metrics_cumulates(session):
    repo = WorldBossRepository(session)
    boss = repo.create(
        code="b", name="B", image_name="", max_hp=100, attack=10, defense=5, speed=5,
    )
    p1 = _create_player(session, 1, "Alice")
    repo.upsert_participation(boss.id, p1, joined=True)

    repo.add_combat_metrics(boss.id, p1, damage_dealt=100, damage_tanked=20, hp_healed=0)
    repo.add_combat_metrics(boss.id, p1, damage_dealt=50, damage_tanked=10, hp_healed=5)

    p = repo.get_participation(boss.id, p1)
    assert p.damage_dealt == 150
    assert p.damage_tanked == 30
    assert p.hp_healed == 5
    assert p.fights_count == 2
