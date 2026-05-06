"""Tests du TitleUnlockService (intégration kill → unlock)."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application.services.title_unlock_service import TitleUnlockService
from app.infrastructure.db.base import Base

# Imports nécessaires pour Base.metadata
from app.infrastructure.db.models.player_model import PlayerModel
from app.infrastructure.db.models.progression_model import PlayerProgressionModel  # noqa: F401
from app.infrastructure.db.models.resource_model import PlayerResourceModel  # noqa: F401
from app.infrastructure.db.models.item_model import ItemDefinitionModel  # noqa: F401
from app.infrastructure.db.models.inventory_model import PlayerInventoryItemModel  # noqa: F401
from app.infrastructure.db.models.equipment_model import PlayerEquipmentItemModel  # noqa: F401
from app.infrastructure.db.models.mob_model import MobDefinitionModel
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

from app.infrastructure.db.repositories.player_kill_repository import PlayerKillRepository
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


def _seed_slime_mob(session) -> None:
    now = datetime.now(UTC)
    mob = MobDefinitionModel(
        code="slime", name="Slime", description="", image_name="",
        family="slime", max_hp=10, current_hp=10, attack=2, defense=1,
        speed=3, crit_chance=0, crit_damage=100, dodge=0, hp_regeneration=0,
        xp_reward=5, gold_reward=2, spawn_weight=1, loot_table_json=None,
        created_at=now, updated_at=now,
    )
    session.add(mob)
    session.commit()


def test_unlock_after_100_kills_of_family(session):
    pid = _create_player(session, 1)
    _seed_slime_mob(session)

    kill_repo = PlayerKillRepository(session)
    title_repo = PlayerTitleRepository(session)
    service = TitleUnlockService(title_repo, kill_repo)

    # 99 kills : pas encore débloqué
    kill_repo.set_kill_count(pid, "slime", 99)
    events = service.check_kills_family(pid, "slime")
    assert events == []

    # 100 kills : débloqué
    kill_repo.set_kill_count(pid, "slime", 100)
    events = service.check_kills_family(pid, "slime")
    assert len(events) == 1
    assert events[0].title.code == "slime_slayer"

    # 101 kills, déjà débloqué → pas de double event
    kill_repo.set_kill_count(pid, "slime", 101)
    events = service.check_kills_family(pid, "slime")
    assert events == []


def test_unlock_only_for_matching_family(session):
    pid = _create_player(session, 1)
    _seed_slime_mob(session)

    kill_repo = PlayerKillRepository(session)
    title_repo = PlayerTitleRepository(session)
    service = TitleUnlockService(title_repo, kill_repo)

    # 100 kills de slime, mais on check pour 'gobelin' → rien
    kill_repo.set_kill_count(pid, "slime", 100)
    events = service.check_kills_family(pid, "gobelin")
    assert events == []


def test_unlock_bourreau_at_500_kills_total(session):
    """500 mobs (toutes familles confondues) → unlock 'bourreau'."""
    pid = _create_player(session, 42)
    _seed_slime_mob(session)

    kill_repo = PlayerKillRepository(session)
    title_repo = PlayerTitleRepository(session)
    service = TitleUnlockService(title_repo, kill_repo)

    kill_repo.set_kill_count(pid, "slime", 499)
    events = service.check_kills_total(pid)
    assert all(e.title.code != "bourreau" for e in events)

    kill_repo.set_kill_count(pid, "slime", 500)
    events = service.check_kills_total(pid)
    assert any(e.title.code == "bourreau" for e in events)


def test_unlock_chasseur_legendaire_per_mob(session):
    """50 kills sur un mob_code → unlock du chasseur_legendaire correspondant."""
    pid = _create_player(session, 99)
    _seed_slime_mob(session)

    kill_repo = PlayerKillRepository(session)
    title_repo = PlayerTitleRepository(session)
    service = TitleUnlockService(title_repo, kill_repo)

    kill_repo.set_kill_count(pid, "slime", 49)
    events = service.check_kills_mob(pid, "slime")
    assert events == []

    kill_repo.set_kill_count(pid, "slime", 50)
    events = service.check_kills_mob(pid, "slime")
    assert len(events) == 1
    assert events[0].title.code == "slime_chasseur_legendaire"


def test_unlock_chasseur_only_targets_specified_mob(session):
    """50 kills slime ne débloque pas le chasseur gobelin."""
    pid = _create_player(session, 100)
    _seed_slime_mob(session)

    kill_repo = PlayerKillRepository(session)
    title_repo = PlayerTitleRepository(session)
    service = TitleUnlockService(title_repo, kill_repo)

    kill_repo.set_kill_count(pid, "slime", 50)
    # Si on check pour 'gobelin', rien ne s'unlock
    events = service.check_kills_mob(pid, "gobelin")
    assert events == []


def test_unlock_intouchable_at_100_dodges(session):
    pid = _create_player(session, 200)
    kill_repo = PlayerKillRepository(session)
    title_repo = PlayerTitleRepository(session)
    service = TitleUnlockService(title_repo, kill_repo)

    events = service.check_dodges_total(pid, 99)
    assert events == []

    events = service.check_dodges_total(pid, 100)
    assert any(e.title.code == "intouchable" for e in events)


def test_unlock_taverne_addict_at_streak_30(session):
    pid = _create_player(session, 300)
    kill_repo = PlayerKillRepository(session)
    title_repo = PlayerTitleRepository(session)
    service = TitleUnlockService(title_repo, kill_repo)

    events = service.check_daily_streak(pid, 29)
    assert events == []

    events = service.check_daily_streak(pid, 30)
    assert any(e.title.code == "taverne_addict" for e in events)
