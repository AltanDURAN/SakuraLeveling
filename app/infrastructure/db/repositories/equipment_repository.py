"""Équipement PORTÉ — vue sur les pièces possédées (`player_gear`) qui ont un
emplacement.

Équipement v2 : une pièce portée est un exemplaire précis (rareté, forge).
L'interface historique (`list_by_player_id`, `equip_item`, `unequip_slot`,
`get_slot`) est conservée pour la trentaine d'appelants qui lisent les stats ;
`equip_item` choisit alors la MEILLEURE copie libre de la pièce demandée.
"""

from __future__ import annotations

from datetime import datetime, UTC

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.domain.entities.player_equipment_item import PlayerEquipmentItem
from app.domain.services.gear_service import rarity_index
from app.infrastructure.db.models.gear_model import PlayerGearModel
from app.infrastructure.db.repositories._mappers import map_item_definition
from app.infrastructure.db.unit_of_work import commit


class EquipmentRepository:
    def __init__(self, session: Session):
        self.session = session

    def _equipped_query(self):
        return (
            select(PlayerGearModel)
            .options(joinedload(PlayerGearModel.item_definition))
            .where(PlayerGearModel.equipped_slot.is_not(None))
            .order_by(PlayerGearModel.equipped_slot.asc())
        )

    def list_by_player_id(self, player_id: int) -> list[PlayerEquipmentItem]:
        models = self.session.execute(
            self._equipped_query().where(PlayerGearModel.player_id == player_id)
        ).scalars().all()
        return [self._to_domain(m) for m in models]

    def list_by_player_ids(self, player_ids: list[int]) -> dict[int, list[PlayerEquipmentItem]]:
        """Variante EN LOT : une seule requête pour N joueurs."""
        if not player_ids:
            return {}
        out: dict[int, list[PlayerEquipmentItem]] = {pid: [] for pid in player_ids}
        models = self.session.execute(
            self._equipped_query().where(PlayerGearModel.player_id.in_(player_ids))
        ).scalars().all()
        for model in models:
            out.setdefault(model.player_id, []).append(self._to_domain(model))
        return out

    def _slot_model(self, player_id: int, slot: str) -> PlayerGearModel | None:
        return self.session.execute(
            select(PlayerGearModel).where(
                PlayerGearModel.player_id == player_id,
                PlayerGearModel.equipped_slot == slot,
            )
        ).scalar_one_or_none()

    def equip_gear(self, player_id: int, gear_id: int, slot: str) -> bool:
        """Porte CET exemplaire dans `slot` (l'occupant éventuel est retiré)."""
        model = self.session.get(PlayerGearModel, gear_id)
        if model is None or model.player_id != player_id or model.listed:
            return False
        current = self._slot_model(player_id, slot)
        if current is not None and current.id != model.id:
            current.equipped_slot = None
            self.session.flush()
        model.equipped_slot = slot
        model.updated_at = datetime.now(UTC)
        commit(self.session)
        return True

    def equip_item(self, player_id: int, item_definition_id: int, slot: str) -> bool:
        """Porte la meilleure copie LIBRE de cette pièce (rareté, puis forge)."""
        free = self.session.execute(
            select(PlayerGearModel).where(
                PlayerGearModel.player_id == player_id,
                PlayerGearModel.item_definition_id == item_definition_id,
                PlayerGearModel.equipped_slot.is_(None),
                PlayerGearModel.listed.is_(False),
            )
        ).scalars().all()
        if not free:
            return False
        best = max(free, key=lambda m: (rarity_index(m.rarity), m.forge_level, -m.id))
        return self.equip_gear(player_id, best.id, slot)

    def unequip_slot(self, player_id: int, slot: str) -> bool:
        """Retire la pièce du slot (elle reste possédée). True si quelque chose
        a été retiré, False si le slot était déjà vide."""
        model = self._slot_model(player_id, slot)
        if model is None:
            return False
        model.equipped_slot = None
        model.updated_at = datetime.now(UTC)
        commit(self.session)
        return True

    def get_slot(self, player_id: int, slot: str) -> PlayerEquipmentItem | None:
        model = self.session.execute(
            self._equipped_query().where(
                PlayerGearModel.player_id == player_id,
                PlayerGearModel.equipped_slot == slot,
            )
        ).scalar_one_or_none()
        return self._to_domain(model) if model else None

    def _to_domain(self, model: PlayerGearModel) -> PlayerEquipmentItem:
        return PlayerEquipmentItem(
            id=model.id,
            player_id=model.player_id,
            slot=model.equipped_slot or "",
            item_definition=map_item_definition(model.item_definition),
            created_at=model.created_at,
            updated_at=model.updated_at,
            rarity=model.rarity,
            forge_level=int(model.forge_level or 0),
            gear_id=model.id,
        )
