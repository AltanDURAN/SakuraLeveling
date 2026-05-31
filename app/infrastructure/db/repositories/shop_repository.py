from datetime import datetime, UTC

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.entities.shop_item import ShopItem
from app.infrastructure.db.models.item_model import ItemDefinitionModel
from app.infrastructure.db.models.shop_item_model import ShopItemModel
from app.infrastructure.db.repositories._mappers import map_item_definition


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
        # Garde contre une ShopItem orpheline (ItemDefinition supprimée).
        # Sans ça, on déréfère un None silencieusement → AttributeError opaque.
        # Cf. audit B3 : aligne le pattern défensif de craft_repository._to_domain.
        if item_model is None:
            raise RuntimeError(
                f"ShopItem id={model.id} référence item_definition_id="
                f"{model.item_definition_id} qui n'existe plus. "
                "Re-seed le contenu (seed_content.py) ou retire l'entrée orpheline."
            )
        item_definition = map_item_definition(item_model)
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
