from datetime import datetime, UTC

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.domain.entities.item_definition import ItemDefinition
from app.domain.entities.player_equipment_item import PlayerEquipmentItem
from app.infrastructure.db.models.equipment_model import PlayerEquipmentItemModel


class EquipmentRepository:
    def __init__(self, session: Session):
        self.session = session

    def list_by_player_id(self, player_id: int) -> list[PlayerEquipmentItem]:
        stmt = (
            select(PlayerEquipmentItemModel)
            .options(joinedload(PlayerEquipmentItemModel.item_definition))
            .where(PlayerEquipmentItemModel.player_id == player_id)
            .order_by(PlayerEquipmentItemModel.slot.asc())
        )

        models = self.session.execute(stmt).scalars().all()
        return [self._to_domain(model) for model in models]

    def equip_item(self, player_id: int, item_definition_id: int, slot: str) -> None:
        stmt = select(PlayerEquipmentItemModel).where(
            PlayerEquipmentItemModel.player_id == player_id,
            PlayerEquipmentItemModel.slot == slot,
        )

        model = self.session.execute(stmt).scalar_one_or_none()
        now = datetime.now(UTC)

        if model is None:
            model = PlayerEquipmentItemModel(
                player_id=player_id,
                item_definition_id=item_definition_id,
                slot=slot,
                created_at=now,
                updated_at=now,
            )
            self.session.add(model)
        else:
            model.item_definition_id = item_definition_id
            model.updated_at = now

        self.session.commit()

    def _to_domain(self, model: PlayerEquipmentItemModel) -> PlayerEquipmentItem:
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

        return PlayerEquipmentItem(
            id=model.id,
            player_id=model.player_id,
            slot=model.slot,
            item_definition=item_definition,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )