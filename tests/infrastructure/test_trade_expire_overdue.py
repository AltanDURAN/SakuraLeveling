"""Tests du bulk expire de trades dépassés (cleanup job)."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application.use_cases.create_trade import CreateTradeUseCase, TradeOffer
from app.domain.entities.trade import TradeStatus
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
from app.infrastructure.db.models.trade_model import TradeItemModel, TradeModel

from app.infrastructure.db.repositories.inventory_repository import InventoryRepository
from app.infrastructure.db.repositories.item_repository import ItemRepository
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.repositories.trade_repository import TradeRepository


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


def _create_player(session, discord_id: int, name: str, gold: int = 100) -> int:
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


def _create_pending_trade(session, initiator_dc: int, target_dc: int) -> int:
    use_case = CreateTradeUseCase(
        player_repository=PlayerRepository(session),
        inventory_repository=InventoryRepository(session),
        item_repository=ItemRepository(session),
        trade_repository=TradeRepository(session),
    )
    initiator = session.query(PlayerModel).filter_by(discord_id=initiator_dc).one()
    target = session.query(PlayerModel).filter_by(discord_id=target_dc).one()
    result = use_case.execute(
        initiator_discord_id=initiator_dc,
        target_discord_id=target_dc,
        initiator_username=initiator.username,
        initiator_display_name=initiator.display_name,
        target_display_name=target.display_name,
        initiator_offer=TradeOffer(gold=10),
        target_request=TradeOffer(gold=20),
    )
    assert result.success
    return result.trade.id


def _force_expired(session, trade_id: int, minutes: int = 1) -> None:
    trade = session.get(TradeModel, trade_id)
    trade.expires_at = datetime.now(UTC) - timedelta(minutes=minutes)
    session.commit()


def test_expire_overdue_marks_only_overdue_trades(session):
    _create_player(session, 1, "Alice")
    _create_player(session, 2, "Bob")
    _create_player(session, 3, "Charlie")

    # Trade 1 : entre Alice et Bob, expirera (par force)
    overdue_id = _create_pending_trade(session, 1, 2)
    _force_expired(session, overdue_id)

    # Trade 2 : entre Charlie (initiator) et Alice, expires_at futur (laissé tel quel)
    fresh_id = _create_pending_trade(session, 3, 1)

    repo = TradeRepository(session)
    affected = repo.expire_overdue_pending()

    assert affected == 1
    assert repo.get_by_id(overdue_id).status == TradeStatus.EXPIRED
    assert repo.get_by_id(fresh_id).status == TradeStatus.PENDING


def test_expire_overdue_is_idempotent(session):
    _create_player(session, 1, "Alice")
    _create_player(session, 2, "Bob")
    overdue_id = _create_pending_trade(session, 1, 2)
    _force_expired(session, overdue_id)

    repo = TradeRepository(session)
    repo.expire_overdue_pending()
    second = repo.expire_overdue_pending()

    assert second == 0


def test_expire_overdue_does_not_touch_already_completed_trades(session):
    _create_player(session, 1, "Alice")
    _create_player(session, 2, "Bob")
    trade_id = _create_pending_trade(session, 1, 2)

    # Marque accepted manuellement, et force expires_at dans le passé
    repo = TradeRepository(session)
    repo.update_status(trade_id, TradeStatus.ACCEPTED, completed=True)
    _force_expired(session, trade_id)

    affected = repo.expire_overdue_pending()

    assert affected == 0
    assert repo.get_by_id(trade_id).status == TradeStatus.ACCEPTED


def test_expire_unblocks_new_trades_between_same_pair(session):
    _create_player(session, 1, "Alice", gold=100)
    _create_player(session, 2, "Bob", gold=100)
    use_case = CreateTradeUseCase(
        player_repository=PlayerRepository(session),
        inventory_repository=InventoryRepository(session),
        item_repository=ItemRepository(session),
        trade_repository=TradeRepository(session),
    )
    repo = TradeRepository(session)

    # 1er trade Alice → Bob
    first = use_case.execute(
        initiator_discord_id=1, target_discord_id=2,
        initiator_username="alice", initiator_display_name="Alice",
        target_display_name="Bob",
        initiator_offer=TradeOffer(gold=10),
        target_request=TradeOffer(gold=20),
    )
    assert first.success

    # 2e tentative tout de suite → refusée
    second_blocked = use_case.execute(
        initiator_discord_id=1, target_discord_id=2,
        initiator_username="alice", initiator_display_name="Alice",
        target_display_name="Bob",
        initiator_offer=TradeOffer(gold=5),
        target_request=TradeOffer(gold=5),
    )
    assert second_blocked.success is False

    # Force expiration + cleanup
    _force_expired(session, first.trade.id)
    repo.expire_overdue_pending()

    # Maintenant la 2e tentative passe
    second_ok = use_case.execute(
        initiator_discord_id=1, target_discord_id=2,
        initiator_username="alice", initiator_display_name="Alice",
        target_display_name="Bob",
        initiator_offer=TradeOffer(gold=5),
        target_request=TradeOffer(gold=5),
    )
    assert second_ok.success is True
