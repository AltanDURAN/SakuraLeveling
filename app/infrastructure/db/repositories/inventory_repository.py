from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.domain.entities.item_definition import ItemDefinition
from app.domain.entities.player_inventory_item import PlayerInventoryItem
from app.infrastructure.db.models.inventory_model import PlayerInventoryItemModel
from app.infrastructure.db.models.item_model import ItemDefinitionModel


class InventoryRepository:
    def __init__(self, session: Session):
        self.session = session

    def list_by_player_id(self, player_id: int) -> list[PlayerInventoryItem]:
        stmt = (
            select(PlayerInventoryItemModel)
            .options(joinedload(PlayerInventoryItemModel.item_definition))
            .where(PlayerInventoryItemModel.player_id == player_id)
            .order_by(PlayerInventoryItemModel.id.asc())
        )

        models = self.session.execute(stmt).scalars().all()
        return [self._to_domain(model) for model in models]

    def add_item(self, player_id: int, item_definition_id: int, quantity: int) -> None:
        stmt = select(PlayerInventoryItemModel).where(
            PlayerInventoryItemModel.player_id == player_id,
            PlayerInventoryItemModel.item_definition_id == item_definition_id,
        )

        model = self.session.execute(stmt).scalar_one_or_none()
        now = datetime.now(timezone.utc)

        if model is None:
            model = PlayerInventoryItemModel(
                player_id=player_id,
                item_definition_id=item_definition_id,
                quantity=quantity,
                created_at=now,
                updated_at=now,
            )
            self.session.add(model)
        else:
            model.quantity += quantity
            model.updated_at = now

        self.session.commit()

    def remove_item(self, player_id: int, item_definition_id: int, quantity: int) -> bool:
        stmt = select(PlayerInventoryItemModel).where(
            PlayerInventoryItemModel.player_id == player_id,
            PlayerInventoryItemModel.item_definition_id == item_definition_id,
        )

        model = self.session.execute(stmt).scalar_one_or_none()

        if model is None or model.quantity < quantity:
            return False

        model.quantity -= quantity
        model.updated_at = datetime.now(timezone.utc)

        if model.quantity == 0:
            self.session.delete(model)

        self.session.commit()
        return True

    def _to_domain(self, model: PlayerInventoryItemModel) -> PlayerInventoryItem:
        item_model = model.item_definition

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
            created_at=item_model.created_at,
            updated_at=item_model.updated_at,
        )

        return PlayerInventoryItem(
            id=model.id,
            player_id=model.player_id,
            item_definition=item_definition,
            quantity=model.quantity,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )