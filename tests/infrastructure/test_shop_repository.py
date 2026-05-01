from datetime import datetime, UTC

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.infrastructure.db.base import Base

from app.infrastructure.db.models.player_model import PlayerModel  # noqa: F401
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

from app.infrastructure.db.repositories.shop_repository import ShopRepository


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


def _create_item(session, code: str = "slime_gel", name: str = "Gelée de Slime") -> int:
    now = datetime.now(UTC)
    item = ItemDefinitionModel(
        code=code,
        name=name,
        description="",
        category="resource",
        rarity="common",
        stackable=True,
        max_stack=None,
        sell_price=0,
        buy_price=None,
        icon=None,
        stat_bonuses_json=None,
        created_at=now,
        updated_at=now,
    )
    session.add(item)
    session.commit()
    return item.id


def test_create_shop_item_persists_all_fields(session):
    item_id = _create_item(session)
    repo = ShopRepository(session)

    shop_item = repo.create(
        item_definition_id=item_id,
        buy_price=10,
        max_sell_price=5,
        min_sell_price=1,
        stock_threshold=50,
    )

    assert shop_item.buy_price == 10
    assert shop_item.max_sell_price == 5
    assert shop_item.min_sell_price == 1
    assert shop_item.stock_threshold == 50
    assert shop_item.current_stock == 0
    assert shop_item.enabled is True
    assert shop_item.item_definition.code == "slime_gel"


def test_get_by_item_code_returns_shop_item(session):
    item_id = _create_item(session, code="slime_gel")
    repo = ShopRepository(session)
    repo.create(
        item_definition_id=item_id,
        buy_price=10,
        max_sell_price=5,
        min_sell_price=1,
        stock_threshold=50,
    )

    found = repo.get_by_item_code("slime_gel")

    assert found is not None
    assert found.item_definition.code == "slime_gel"


def test_get_by_item_code_returns_none_when_missing(session):
    repo = ShopRepository(session)

    assert repo.get_by_item_code("absent") is None


def test_update_modifies_only_provided_fields(session):
    item_id = _create_item(session)
    repo = ShopRepository(session)
    shop_item = repo.create(
        item_definition_id=item_id,
        buy_price=10,
        max_sell_price=5,
        min_sell_price=1,
        stock_threshold=50,
    )

    updated = repo.update(shop_item.id, buy_price=15, enabled=False)

    assert updated.buy_price == 15
    assert updated.enabled is False
    # Champs non modifiés conservés
    assert updated.max_sell_price == 5
    assert updated.min_sell_price == 1
    assert updated.stock_threshold == 50


def test_add_to_stock_increments(session):
    item_id = _create_item(session)
    repo = ShopRepository(session)
    shop_item = repo.create(
        item_definition_id=item_id,
        buy_price=10,
        max_sell_price=5,
        min_sell_price=1,
        stock_threshold=50,
    )

    updated = repo.add_to_stock(shop_item.id, 30)
    assert updated.current_stock == 30

    updated = repo.add_to_stock(shop_item.id, 20)
    assert updated.current_stock == 50


def test_set_stock_overrides(session):
    item_id = _create_item(session)
    repo = ShopRepository(session)
    shop_item = repo.create(
        item_definition_id=item_id,
        buy_price=10,
        max_sell_price=5,
        min_sell_price=1,
        stock_threshold=50,
    )
    repo.add_to_stock(shop_item.id, 100)

    updated = repo.set_stock(shop_item.id, 0)

    assert updated.current_stock == 0


def test_set_stock_clamps_to_zero_when_negative(session):
    item_id = _create_item(session)
    repo = ShopRepository(session)
    shop_item = repo.create(
        item_definition_id=item_id,
        buy_price=10,
        max_sell_price=5,
        min_sell_price=1,
        stock_threshold=50,
    )

    updated = repo.set_stock(shop_item.id, -5)

    assert updated.current_stock == 0


def test_delete_removes_shop_item(session):
    item_id = _create_item(session)
    repo = ShopRepository(session)
    shop_item = repo.create(
        item_definition_id=item_id,
        buy_price=10,
        max_sell_price=5,
        min_sell_price=1,
        stock_threshold=50,
    )

    assert repo.delete(shop_item.id) is True
    assert repo.get_by_item_code("slime_gel") is None


def test_list_all_only_enabled_filters(session):
    item_id_a = _create_item(session, code="a", name="A")
    item_id_b = _create_item(session, code="b", name="B")
    repo = ShopRepository(session)
    a = repo.create(item_definition_id=item_id_a, buy_price=1, max_sell_price=1, min_sell_price=0, stock_threshold=10)
    repo.create(item_definition_id=item_id_b, buy_price=1, max_sell_price=1, min_sell_price=0, stock_threshold=10)
    repo.update(a.id, enabled=False)

    enabled_only = repo.list_all(only_enabled=True)
    all_items = repo.list_all(only_enabled=False)

    assert len(enabled_only) == 1
    assert enabled_only[0].item_definition.code == "b"
    assert len(all_items) == 2
