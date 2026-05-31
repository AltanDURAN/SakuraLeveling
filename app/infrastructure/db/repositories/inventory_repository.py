from datetime import datetime, UTC

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.domain.entities.player_inventory_item import PlayerInventoryItem
from app.infrastructure.db.models.inventory_model import PlayerInventoryItemModel
from app.infrastructure.db.models.item_model import ItemDefinitionModel
from app.infrastructure.db.repositories._mappers import map_item_definition


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
        # Garde défensif : quantité <= 0 = no-op (préviens l'usage négatif
        # qui décrementerait l'inventaire).
        if quantity <= 0:
            return

        stmt = select(PlayerInventoryItemModel).where(
            PlayerInventoryItemModel.player_id == player_id,
            PlayerInventoryItemModel.item_definition_id == item_definition_id,
        )

        model = self.session.execute(stmt).scalar_one_or_none()
        now = datetime.now(UTC)

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
        # Garde défensif : qty négative ferait un increment via le `-= quantity`.
        # Qty zéro est un no-op qui pourrait simuler un succès faux.
        if quantity <= 0:
            return False

        stmt = select(PlayerInventoryItemModel).where(
            PlayerInventoryItemModel.player_id == player_id,
            PlayerInventoryItemModel.item_definition_id == item_definition_id,
        )

        model = self.session.execute(stmt).scalar_one_or_none()

        if model is None or model.quantity < quantity:
            return False

        model.quantity -= quantity
        model.updated_at = datetime.now(UTC)

        if model.quantity == 0:
            self.session.delete(model)

        self.session.commit()
        return True

    def _to_domain(self, model: PlayerInventoryItemModel) -> PlayerInventoryItem:
        item_definition = map_item_definition(model.item_definition)

        return PlayerInventoryItem(
            id=model.id,
            player_id=model.player_id,
            item_definition=item_definition,
            quantity=model.quantity,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )