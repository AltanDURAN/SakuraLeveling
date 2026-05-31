from datetime import datetime, UTC

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.domain.entities.player_equipment_item import PlayerEquipmentItem
from app.infrastructure.db.models.equipment_model import PlayerEquipmentItemModel
from app.infrastructure.db.repositories._mappers import map_item_definition


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

    def unequip_slot(self, player_id: int, slot: str) -> bool:
        """Retire l'équipement du slot spécifié. Renvoie True si quelque chose
        a été retiré, False si le slot était déjà vide."""
        stmt = select(PlayerEquipmentItemModel).where(
            PlayerEquipmentItemModel.player_id == player_id,
            PlayerEquipmentItemModel.slot == slot,
        )
        model = self.session.execute(stmt).scalar_one_or_none()
        if model is None:
            return False

        self.session.delete(model)
        self.session.commit()
        return True

    def get_slot(self, player_id: int, slot: str):
        stmt = (
            select(PlayerEquipmentItemModel)
            .options(joinedload(PlayerEquipmentItemModel.item_definition))
            .where(
                PlayerEquipmentItemModel.player_id == player_id,
                PlayerEquipmentItemModel.slot == slot,
            )
        )
        model = self.session.execute(stmt).scalar_one_or_none()
        if model is None:
            return None
        return self._to_domain(model)

    def _to_domain(self, model: PlayerEquipmentItemModel) -> PlayerEquipmentItem:
        item_definition = map_item_definition(model.item_definition)

        return PlayerEquipmentItem(
            id=model.id,
            player_id=model.player_id,
            slot=model.slot,
            item_definition=item_definition,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )