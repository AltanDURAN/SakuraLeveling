from datetime import datetime, UTC

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.entities.item_definition import ItemDefinition
from app.domain.entities.shop_item import ShopItem
from app.infrastructure.db.models.item_model import ItemDefinitionModel
from app.infrastructure.db.models.shop_item_model import ShopItemModel


class ShopRepository:
    def __init__(self, session: Session):
        self.session = session

    def list_all(self, only_enabled: bool = False) -> list[ShopItem]:
        stmt = select(ShopItemModel)
        if only_enabled:
            stmt = stmt.where(ShopItemModel.enabled.is_(True))
        stmt = stmt.order_by(ShopItemModel.id.asc())

        models = self.session.execute(stmt).scalars().all()
        return [self._to_domain(model) for model in models]

    def get_by_item_code(self, item_code: str) -> ShopItem | None:
        stmt = (
            select(ShopItemModel)
            .join(
                ItemDefinitionModel,
                ItemDefinitionModel.id == ShopItemModel.item_definition_id,
            )
            .where(ItemDefinitionModel.code == item_code)
        )
        model = self.session.execute(stmt).scalar_one_or_none()
        if model is None:
            return None
        return self._to_domain(model)

    def create(
        self,
        item_definition_id: int,
        buy_price: int,
        max_sell_price: int,
        min_sell_price: int,
        stock_threshold: int,
        current_stock: int = 0,
        enabled: bool = True,
    ) -> ShopItem:
        now = datetime.now(UTC)
        model = ShopItemModel(
            item_definition_id=item_definition_id,
            buy_price=buy_price,
            max_sell_price=max_sell_price,
            min_sell_price=min_sell_price,
            stock_threshold=stock_threshold,
            current_stock=current_stock,
            enabled=enabled,
            created_at=now,
            updated_at=now,
        )
        self.session.add(model)
        self.session.commit()
        self.session.refresh(model)
        return self._to_domain(model)

    def update(
        self,
        shop_item_id: int,
        *,
        buy_price: int | None = None,
        max_sell_price: int | None = None,
        min_sell_price: int | None = None,
        stock_threshold: int | None = None,
        enabled: bool | None = None,
    ) -> ShopItem | None:
        model = self.session.get(ShopItemModel, shop_item_id)
        if model is None:
            return None

        if buy_price is not None:
            model.buy_price = buy_price
        if max_sell_price is not None:
            model.max_sell_price = max_sell_price
        if min_sell_price is not None:
            model.min_sell_price = min_sell_price
        if stock_threshold is not None:
            model.stock_threshold = stock_threshold
        if enabled is not None:
            model.enabled = enabled

        model.updated_at = datetime.now(UTC)
        self.session.commit()
        self.session.refresh(model)
        return self._to_domain(model)

    def delete(self, shop_item_id: int) -> bool:
        model = self.session.get(ShopItemModel, shop_item_id)
        if model is None:
            return False
        self.session.delete(model)
        self.session.commit()
        return True

    def add_to_stock(self, shop_item_id: int, quantity: int) -> ShopItem | None:
        model = self.session.get(ShopItemModel, shop_item_id)
        if model is None:
            return None
        model.current_stock = max(0, model.current_stock + quantity)
        model.updated_at = datetime.now(UTC)
        self.session.commit()
        self.session.refresh(model)
        return self._to_domain(model)

    def set_stock(self, shop_item_id: int, stock: int) -> ShopItem | None:
        model = self.session.get(ShopItemModel, shop_item_id)
        if model is None:
            return None
        model.current_stock = max(0, stock)
        model.updated_at = datetime.now(UTC)
        self.session.commit()
        self.session.refresh(model)
        return self._to_domain(model)

    def _to_domain(self, model: ShopItemModel) -> ShopItem:
        item_model = self.session.get(ItemDefinitionModel, model.item_definition_id)
        item_definition = ItemDefinition(
            id=item_model.id,
            code=item_model.code,
            name=item_model.name,
            description=item_model.description,
            category=item_model.category,
            rarity=item_model.rarity,
            stackable=item_model.stackable,
            max_stack=item_model.max_stack,
            sell_price=item_model.sell_price,
            buy_price=item_model.buy_price,
            icon=item_model.icon,
            stat_bonuses=item_model.stat_bonuses_json,
            equipment_slot=item_model.equipment_slot,
            requires_two_hands=bool(item_model.requires_two_hands or False),
            family=getattr(item_model, "family", "") or "",
            created_at=item_model.created_at,
            updated_at=item_model.updated_at,
        )
        return ShopItem(
            id=model.id,
            item_definition=item_definition,
            buy_price=model.buy_price,
            max_sell_price=model.max_sell_price,
            min_sell_price=model.min_sell_price,
            stock_threshold=model.stock_threshold,
            current_stock=model.current_stock,
            enabled=model.enabled,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )
