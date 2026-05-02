"""Tests de hardening de InventoryRepository : refus des quantités ≤ 0.

Sécurité : si `quantity` est négatif ou nul, les opérations sont des no-ops
pour éviter qu'un caller buggué décrémente l'inventaire à la place d'incrémenter
(ou inversement).
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.infrastructure.db.base import Base

from app.infrastructure.db.models.player_model import PlayerModel
from app.infrastructure.db.models.progression_model import PlayerProgressionModel  # noqa: F401
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

from app.infrastructure.db.repositories.inventory_repository import InventoryRepository


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


def _create_player(session, discord_id: int = 1) -> int:
    now = datetime.now(UTC)
    player = PlayerModel(
        discord_id=discord_id, username="alice", display_name="Alice",
        created_at=now, updated_at=now, last_seen_at=now,
    )
    session.add(player)
    session.commit()
    return player.id


def _create_item(session, code: str = "iron") -> int:
    now = datetime.now(UTC)
    item = ItemDefinitionModel(
        code=code, name=code, description="", category="resource", rarity="common",
        stackable=True, max_stack=None, sell_price=0, buy_price=None,
        icon=None, stat_bonuses_json=None, equipment_slot=None,
        requires_two_hands=False,
        created_at=now, updated_at=now,
    )
    session.add(item)
    session.commit()
    return item.id


def _quantity(session, player_id: int, code: str) -> int:
    items = InventoryRepository(session).list_by_player_id(player_id)
    for i in items:
        if i.item_definition.code == code:
            return i.quantity
    return 0


def test_add_item_with_negative_quantity_is_noop(session):
    pid = _create_player(session)
    item_id = _create_item(session)
    repo = InventoryRepository(session)

    repo.add_item(pid, item_id, 5)
    repo.add_item(pid, item_id, -3)  # ne devrait pas décrémenter

    assert _quantity(session, pid, "iron") == 5


def test_add_item_with_zero_quantity_is_noop(session):
    pid = _create_player(session)
    item_id = _create_item(session)
    repo = InventoryRepository(session)

    repo.add_item(pid, item_id, 0)

    assert _quantity(session, pid, "iron") == 0  # pas créé


def test_remove_item_with_negative_quantity_returns_false_no_change(session):
    pid = _create_player(session)
    item_id = _create_item(session)
    repo = InventoryRepository(session)
    repo.add_item(pid, item_id, 5)

    success = repo.remove_item(pid, item_id, -3)

    assert success is False
    assert _quantity(session, pid, "iron") == 5  # pas modifié


def test_remove_item_with_zero_quantity_returns_false(session):
    pid = _create_player(session)
    item_id = _create_item(session)
    repo = InventoryRepository(session)
    repo.add_item(pid, item_id, 5)

    success = repo.remove_item(pid, item_id, 0)

    assert success is False
    assert _quantity(session, pid, "iron") == 5
