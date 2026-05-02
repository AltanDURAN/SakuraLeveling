"""Tests d'intégration de TransferGoldUseCase (commande /pay)."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application.use_cases.transfer_gold import TransferGoldUseCase
from app.infrastructure.db.base import Base

# Imports nécessaires pour Base.metadata
from app.infrastructure.db.models.player_model import PlayerModel
from app.infrastructure.db.models.progression_model import PlayerProgressionModel  # noqa: F401
from app.infrastructure.db.models.resource_model import PlayerResourceModel
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


def _create_player(session, discord_id: int, name: str, gold: int = 0) -> int:
    now = datetime.now(UTC)
    player = PlayerModel(
        discord_id=discord_id, username=name.lower(), display_name=name,
        created_at=now, updated_at=now, last_seen_at=now,
    )
    session.add(player)
    session.flush()
    session.add_all([
        PlayerProgressionModel(
            player_id=player.id, level=1, xp=0, skill_points=0,
            created_at=now, updated_at=now,
        ),
        PlayerResourceModel(
            player_id=player.id, gold=gold, daily_streak=0,
            created_at=now, updated_at=now,
        ),
    ])
    session.commit()
    return player.id


def _gold(session, player_id: int) -> int:
    res = session.get(PlayerResourceModel, player_id)
    return res.gold if res else 0


def _make_use_case(session) -> TransferGoldUseCase:
    return TransferGoldUseCase(PlayerRepository(session))


def test_transfer_succeeds_and_moves_gold(session):
    a = _create_player(session, 1, "Alice", gold=100)
    b = _create_player(session, 2, "Bob", gold=50)

    result = _make_use_case(session).execute(
        sender_discord_id=1, sender_username="alice", sender_display_name="Alice",
        receiver_discord_id=2, receiver_display_name="Bob",
        amount=30,
    )

    assert result.success is True
    assert _gold(session, a) == 70
    assert _gold(session, b) == 80
    assert result.amount == 30
    assert result.sender_balance_after == 70


def test_transfer_rejects_zero_amount(session):
    _create_player(session, 1, "Alice", gold=100)
    _create_player(session, 2, "Bob")

    result = _make_use_case(session).execute(
        sender_discord_id=1, sender_username="alice", sender_display_name="Alice",
        receiver_discord_id=2, receiver_display_name="Bob",
        amount=0,
    )

    assert result.success is False
    assert "positif" in result.message.lower()


def test_transfer_rejects_negative_amount(session):
    a = _create_player(session, 1, "Alice", gold=100)
    b = _create_player(session, 2, "Bob", gold=50)

    result = _make_use_case(session).execute(
        sender_discord_id=1, sender_username="alice", sender_display_name="Alice",
        receiver_discord_id=2, receiver_display_name="Bob",
        amount=-50,
    )

    assert result.success is False
    # Aucun déplacement
    assert _gold(session, a) == 100
    assert _gold(session, b) == 50


def test_transfer_rejects_self_payment(session):
    _create_player(session, 1, "Alice", gold=100)

    result = _make_use_case(session).execute(
        sender_discord_id=1, sender_username="alice", sender_display_name="Alice",
        receiver_discord_id=1, receiver_display_name="Alice",
        amount=10,
    )

    assert result.success is False


def test_transfer_rejects_when_receiver_has_no_profile(session):
    _create_player(session, 1, "Alice", gold=100)

    result = _make_use_case(session).execute(
        sender_discord_id=1, sender_username="alice", sender_display_name="Alice",
        receiver_discord_id=999,  # n'existe pas
        receiver_display_name="Ghost",
        amount=10,
    )

    assert result.success is False
    assert "profil" in result.message.lower()


def test_transfer_rejects_insufficient_funds(session):
    a = _create_player(session, 1, "Alice", gold=10)
    b = _create_player(session, 2, "Bob", gold=0)

    result = _make_use_case(session).execute(
        sender_discord_id=1, sender_username="alice", sender_display_name="Alice",
        receiver_discord_id=2, receiver_display_name="Bob",
        amount=50,
    )

    assert result.success is False
    assert "fonds" in result.message.lower() or "insuffisant" in result.message.lower()
    # Aucun déplacement
    assert _gold(session, a) == 10
    assert _gold(session, b) == 0


def test_transfer_with_exact_balance_succeeds(session):
    a = _create_player(session, 1, "Alice", gold=42)
    b = _create_player(session, 2, "Bob")

    result = _make_use_case(session).execute(
        sender_discord_id=1, sender_username="alice", sender_display_name="Alice",
        receiver_discord_id=2, receiver_display_name="Bob",
        amount=42,
    )

    assert result.success is True
    assert _gold(session, a) == 0
    assert _gold(session, b) == 42
