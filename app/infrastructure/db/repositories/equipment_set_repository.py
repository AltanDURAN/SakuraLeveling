"""Repository pour les sets d'équipement nommés (loadouts)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, UTC

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.infrastructure.db.models.equipment_set_model import (
    PlayerEquipmentSetItemModel,
    PlayerEquipmentSetModel,
)
from app.infrastructure.db.repositories._mappers import map_item_definition


@dataclass
class EquipmentSetItem:
    slot: str
    item_definition: ItemDefinition


@dataclass
class EquipmentSet:
    id: int
    player_id: int
    name: str
    items: list[EquipmentSetItem] = field(default_factory=list)


class EquipmentSetRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_for_player(self, player_id: int) -> list[EquipmentSet]:
        stmt = (
            select(PlayerEquipmentSetModel)
            .options(
                joinedload(PlayerEquipmentSetModel.items)
                .joinedload(PlayerEquipmentSetItemModel.item_definition),
            )
            .where(PlayerEquipmentSetModel.player_id == player_id)
            .order_by(PlayerEquipmentSetModel.name.asc())
        )
        models = self.session.execute(stmt).unique().scalars().all()
        return [self._to_domain(m) for m in models]

    def get_by_name(
        self, player_id: int, name: str,
    ) -> EquipmentSet | None:
        stmt = (
            select(PlayerEquipmentSetModel)
            .options(
                joinedload(PlayerEquipmentSetModel.items)
                .joinedload(PlayerEquipmentSetItemModel.item_definition),
            )
            .where(
                PlayerEquipmentSetModel.player_id == player_id,
                PlayerEquipmentSetModel.name == name,
            )
        )
        m = self.session.execute(stmt).unique().scalar_one_or_none()
        return self._to_domain(m) if m else None

    def create(
        self,
        player_id: int,
        name: str,
        items: list[tuple[str, int]],
    ) -> EquipmentSet:
        """`items` : liste de (slot, item_definition_id)."""
        now = datetime.now(UTC)
        model = PlayerEquipmentSetModel(
            player_id=player_id, name=name,
            created_at=now, updated_at=now,
        )
        self.session.add(model)
        self.session.flush()
        for slot, item_def_id in items:
            self.session.add(PlayerEquipmentSetItemModel(
                equipment_set_id=model.id,
                slot=slot,
                item_definition_id=item_def_id,
            ))
        self.session.commit()
        # Recharge avec les relations
        return self.get_by_name(player_id, name)  # type: ignore[return-value]

    def delete(self, player_id: int, name: str) -> bool:
        stmt = select(PlayerEquipmentSetModel).where(
            PlayerEquipmentSetModel.player_id == player_id,
            PlayerEquipmentSetModel.name == name,
        )
        m = self.session.execute(stmt).scalar_one_or_none()
        if m is None:
            return False
        self.session.delete(m)
        self.session.commit()
        return True

    def delete_for_player(self, player_id: int) -> int:
        """Purge tous les sets d'un joueur (utilisé par /admin reset_player)."""
        stmt = select(PlayerEquipmentSetModel).where(
            PlayerEquipmentSetModel.player_id == player_id,
        )
        models = self.session.execute(stmt).scalars().all()
        count = 0
        for m in models:
            self.session.delete(m)
            count += 1
        self.session.commit()
        return count

    def _to_domain(
        self, model: PlayerEquipmentSetModel,
    ) -> EquipmentSet:
        items: list[EquipmentSetItem] = []
        for it in model.items:
            items.append(EquipmentSetItem(
                slot=it.slot,
                item_definition=map_item_definition(it.item_definition),
            ))
        return EquipmentSet(
            id=model.id, player_id=model.player_id,
            name=model.name, items=items,
        )
