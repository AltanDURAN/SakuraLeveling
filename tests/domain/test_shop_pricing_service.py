from datetime import UTC, datetime

from app.domain.entities.item_definition import ItemDefinition
from app.domain.entities.shop_item import ShopItem
from app.domain.services.shop_pricing_service import ShopPricingService


def _make_item_definition() -> ItemDefinition:
    now = datetime.now(UTC)
    return ItemDefinition(
        id=1,
        code="slime_gel",
        name="Gelée de Slime",
        description="",
        category="resource",
        rarity="common",
        stackable=True,
        max_stack=None,
        sell_price=0,
        buy_price=None,
        icon=None,
        stat_bonuses=None,
        created_at=now,
        updated_at=now,
    )


def _make_shop_item(
    buy_price: int = 10,
    max_sell_price: int = 5,
    min_sell_price: int = 1,
    stock_threshold: int = 100,
    current_stock: int = 0,
) -> ShopItem:
    now = datetime.now(UTC)
    return ShopItem(
        id=1,
        item_definition=_make_item_definition(),
        buy_price=buy_price,
        max_sell_price=max_sell_price,
        min_sell_price=min_sell_price,
        stock_threshold=stock_threshold,
        current_stock=current_stock,
        enabled=True,
        created_at=now,
        updated_at=now,
    )


def test_sell_price_at_zero_stock_returns_max():
    service = ShopPricingService()
    item = _make_shop_item(max_sell_price=10, min_sell_price=1, current_stock=0)

    assert service.current_sell_price(item) == 10


def test_sell_price_at_threshold_returns_min():
    service = ShopPricingService()
    item = _make_shop_item(max_sell_price=10, min_sell_price=1, stock_threshold=100, current_stock=100)

    assert service.current_sell_price(item) == 1


def test_sell_price_above_threshold_stays_at_min():
    service = ShopPricingService()
    item = _make_shop_item(max_sell_price=10, min_sell_price=1, stock_threshold=100, current_stock=500)

    assert service.current_sell_price(item) == 1


def test_sell_price_interpolates_linearly():
    service = ShopPricingService()
    # Plage 100→0, threshold 100. À stock 50, prix attendu = 50.
    item = _make_shop_item(max_sell_price=100, min_sell_price=0, stock_threshold=100, current_stock=50)

    assert service.current_sell_price(item) == 50


def test_total_buy_cost_is_linear():
    service = ShopPricingService()
    item = _make_shop_item(buy_price=15)

    assert service.total_buy_cost(item, 0) == 0
    assert service.total_buy_cost(item, 1) == 15
    assert service.total_buy_cost(item, 10) == 150


def test_sell_price_with_zero_threshold_returns_max():
    service = ShopPricingService()
    item = _make_shop_item(max_sell_price=10, min_sell_price=1, stock_threshold=0, current_stock=999)

    # Threshold 0 = pas de décroissance, prix toujours max.
    assert service.current_sell_price(item) == 10
