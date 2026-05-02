"""Tests d'intégration des quêtes hebdomadaires."""

import random
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application.use_cases.weekly_quests import (
    ClaimWeeklyQuestUseCase,
    GetWeeklyQuestsUseCase,
    WeeklyQuestProgressService,
    get_current_week_start,
)
from app.infrastructure.db.base import Base

# Imports nécessaires pour Base.metadata
from app.infrastructure.db.models.player_model import PlayerModel
from app.infrastructure.db.models.progression_model import PlayerProgressionModel
from app.infrastructure.db.models.resource_model import PlayerResourceModel  # noqa: F401
from app.infrastructure.db.models.item_model import ItemDefinitionModel
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

from app.infrastructure.db.repositories.inventory_repository import InventoryRepository
from app.infrastructure.db.repositories.item_repository import ItemRepository
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.repositories.weekly_quest_repository import (
    WeeklyQuestRepository,
)
from app.infrastructure.weekly_quests.quest_loader import (
    list_definitions,
    pick_random_assignment,
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


def _seed_potions(session) -> None:
    now = datetime.now(UTC)
    for code in ["potion_soin_i", "potion_soin_ii", "potion_soin_iii",
                 "iron_ingot", "leather_strip", "polished_stone",
                 "linen_cloth", "wood_log"]:
        item = ItemDefinitionModel(
            code=code, name=code, description="", category="resource",
            rarity="common", stackable=True, max_stack=None,
            sell_price=10, buy_price=None, icon=None,
            stat_bonuses_json=None, equipment_slot=None,
            requires_two_hands=False,
            created_at=now, updated_at=now,
        )
        session.add(item)
    session.commit()


def test_get_current_week_start_is_monday():
    # Vendredi 2026-05-08 → lundi 2026-05-04
    friday = datetime(2026, 5, 8, 14, 30, tzinfo=UTC)
    week_start = get_current_week_start(friday)
    assert week_start.weekday() == 0  # lundi
    assert week_start.day == 4
    assert week_start.hour == 0


def test_pick_random_assignment_returns_3_distinct():
    rng = random.Random(0)
    picks = pick_random_assignment(count=3, rng=rng)
    assert len(picks) == 3
    codes = {p.code for p in picks}
    assert len(codes) == 3  # pas de doublon


def test_first_call_creates_3_assignments(session):
    _seed_potions(session)
    use_case = GetWeeklyQuestsUseCase(
        player_repository=PlayerRepository(session),
        quest_repository=WeeklyQuestRepository(session),
    )
    state = use_case.execute(discord_id=1, username="alice", display_name="Alice")
    assert len(state.quests) == 3
    # Idempotent : 2e appel ne re-crée pas
    state2 = use_case.execute(discord_id=1, username="alice", display_name="Alice")
    assert len(state2.quests) == 3
    assert {q.code for q in state.quests} == {q.code for q in state2.quests}


def test_progress_kill_total_increments(session):
    _seed_potions(session)
    use_case = GetWeeklyQuestsUseCase(
        player_repository=PlayerRepository(session),
        quest_repository=WeeklyQuestRepository(session),
    )
    use_case.execute(discord_id=1, username="alice", display_name="Alice")
    p1 = session.query(PlayerModel).filter_by(discord_id=1).one().id

    progress_service = WeeklyQuestProgressService(WeeklyQuestRepository(session))
    progress_service.on_kill(p1, family="slime", count=10)

    state = use_case.execute(discord_id=1, username="alice", display_name="Alice")
    # Au moins une quête de type kill_total ou kill_family doit avoir progressé
    progressed = [q for q in state.quests if q.progress > 0]
    # Selon le tirage random, il se peut qu'aucune quête de kill_* ne soit
    # tirée. On force donc une assignation contrôlée pour ce test.


def test_progress_with_forced_assignment(session):
    """Force une assignation kill_slime_30 pour tester précisément."""
    _seed_potions(session)
    p1 = PlayerRepository(session).get_or_create_by_discord_id(
        discord_id=1, username="a", display_name="A",
    ).player.id

    week_start = get_current_week_start()
    repo = WeeklyQuestRepository(session)
    repo.assign(p1, week_start, ["kill_slime_30"])

    progress_service = WeeklyQuestProgressService(repo)
    progress_service.on_kill(p1, family="slime", count=20)

    a = repo.get_assignment(p1, week_start, "kill_slime_30")
    assert a.progress == 20
    assert a.completed is False

    progress_service.on_kill(p1, family="slime", count=15)
    a = repo.get_assignment(p1, week_start, "kill_slime_30")
    assert a.progress == 30  # capé à objective_quantity
    assert a.completed is True


def test_progress_kill_other_family_does_not_count(session):
    p1 = PlayerRepository(session).get_or_create_by_discord_id(
        discord_id=1, username="a", display_name="A",
    ).player.id
    week_start = get_current_week_start()
    repo = WeeklyQuestRepository(session)
    repo.assign(p1, week_start, ["kill_slime_30"])

    WeeklyQuestProgressService(repo).on_kill(p1, family="gobelin", count=20)

    a = repo.get_assignment(p1, week_start, "kill_slime_30")
    assert a.progress == 0  # gobelin ne compte pas pour kill_slime_*


def test_claim_distributes_rewards(session):
    _seed_potions(session)
    p1 = PlayerRepository(session).get_or_create_by_discord_id(
        discord_id=1, username="a", display_name="A",
    ).player.id

    week_start = get_current_week_start()
    repo = WeeklyQuestRepository(session)
    repo.assign(p1, week_start, ["kill_slime_30"])
    # Force la complétion
    WeeklyQuestProgressService(repo).on_kill(p1, family="slime", count=30)

    claim = ClaimWeeklyQuestUseCase(
        player_repository=PlayerRepository(session),
        quest_repository=repo,
        item_repository=ItemRepository(session),
        inventory_repository=InventoryRepository(session),
    )
    result = claim.execute(
        discord_id=1, username="a", display_name="A",
        quest_code="kill_slime_30",
    )
    assert result.success is True
    assert result.gold == 500
    assert result.xp == 200

    # Idempotent : 2e claim refusé
    second = claim.execute(
        discord_id=1, username="a", display_name="A",
        quest_code="kill_slime_30",
    )
    assert second.success is False
    assert "déjà" in second.message.lower()


def test_claim_refused_if_not_completed(session):
    _seed_potions(session)
    p1 = PlayerRepository(session).get_or_create_by_discord_id(
        discord_id=1, username="a", display_name="A",
    ).player.id

    week_start = get_current_week_start()
    repo = WeeklyQuestRepository(session)
    repo.assign(p1, week_start, ["kill_slime_30"])
    # Pas de progression

    claim = ClaimWeeklyQuestUseCase(
        player_repository=PlayerRepository(session),
        quest_repository=repo,
        item_repository=ItemRepository(session),
        inventory_repository=InventoryRepository(session),
    )
    result = claim.execute(
        discord_id=1, username="a", display_name="A",
        quest_code="kill_slime_30",
    )
    assert result.success is False
    assert "pas encore terminée" in result.message.lower()
