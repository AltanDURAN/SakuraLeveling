"""Pièces d'équipement possédées (une ligne = un exemplaire)."""

from __future__ import annotations

from datetime import datetime, UTC

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.domain.entities.player_gear import PlayerGear
from app.domain.services.gear_service import Rarity, clamp_forge, rarity_index
from app.infrastructure.db.models.gear_model import PlayerGearModel
from app.infrastructure.db.repositories._mappers import map_item_definition
from app.infrastructure.db.unit_of_work import commit as commit_session


class GearRepository:
    def __init__(self, session: Session):
        self.session = session

    # ------------------------------------------------------------ lecture --
    def _query(self):
        return select(PlayerGearModel).options(joinedload(PlayerGearModel.item_definition))

    def get(self, gear_id: int) -> PlayerGear | None:
        model = self.session.execute(
            self._query().where(PlayerGearModel.id == gear_id)
        ).scalar_one_or_none()
        return self._to_domain(model) if model else None

    def list_owned(self, player_id: int, include_listed: bool = False) -> list[PlayerGear]:
        """Les pièces du joueur, les plus rares d'abord.

        Une pièce EN VENTE à la brocante est exclue par défaut : tant que
        l'annonce court, elle ne se porte, ne se fusionne ni ne s'échange."""
        stmt = self._query().where(PlayerGearModel.player_id == player_id)
        if not include_listed:
            stmt = stmt.where(PlayerGearModel.listed.is_(False))
        models = self.session.execute(stmt).scalars().all()
        gear = [self._to_domain(m) for m in models]
        return sorted(
            gear,
            key=lambda g: (-rarity_index(g.rarity), -g.forge_level, g.item_definition.name, g.id),
        )

    def list_copies(self, player_id: int, item_definition_id: int, rarity: str | None = None) -> list[PlayerGear]:
        return [
            g for g in self.list_owned(player_id)
            if g.item_definition.id == item_definition_id and (rarity is None or g.rarity == rarity)
        ]

    # ------------------------------------------------------------ écriture --
    def add(self, player_id: int, item_definition_id: int, rarity: str = Rarity.COMMON,
            forge_level: int = 0, source: str = "drop", commit: bool = True) -> PlayerGear:
        now = datetime.now(UTC)
        model = PlayerGearModel(
            player_id=player_id, item_definition_id=item_definition_id,
            rarity=Rarity(rarity).value, forge_level=clamp_forge(forge_level),
            source=source, created_at=now, updated_at=now,
        )
        self.session.add(model)
        if commit:
            commit_session(self.session)
        else:
            self.session.flush()
        self.session.refresh(model)
        return self._to_domain(model)

    def remove(self, gear_id: int, commit: bool = True) -> bool:
        model = self.session.get(PlayerGearModel, gear_id)
        if model is None:
            return False
        self.session.delete(model)
        if commit:
            commit_session(self.session)
        return True

    def transfer(self, gear_id: int, new_player_id: int, commit: bool = True) -> bool:
        """Change de propriétaire (échange, brocante) ; la pièce arrive déséquipée."""
        model = self.session.get(PlayerGearModel, gear_id)
        if model is None:
            return False
        model.player_id = new_player_id
        model.equipped_slot = None
        model.listed = False
        model.source = "trade"
        model.updated_at = datetime.now(UTC)
        if commit:
            commit_session(self.session)
        return True

    def set_slot(self, gear_id: int, slot: str | None, commit: bool = True) -> None:
        model = self.session.get(PlayerGearModel, gear_id)
        if model is None:
            return
        model.equipped_slot = slot
        model.updated_at = datetime.now(UTC)
        if commit:
            commit_session(self.session)

    def set_listed(self, gear_id: int, listed: bool, commit: bool = True) -> None:
        model = self.session.get(PlayerGearModel, gear_id)
        if model is None:
            return
        model.listed = listed
        model.updated_at = datetime.now(UTC)
        if commit:
            commit_session(self.session)

    def increment_forge(self, gear_id: int, amount: int = 1) -> int:
        model = self.session.get(PlayerGearModel, gear_id)
        if model is None:
            return 0
        model.forge_level = clamp_forge(model.forge_level + amount)
        model.updated_at = datetime.now(UTC)
        commit_session(self.session)
        return model.forge_level

    def _to_domain(self, model: PlayerGearModel) -> PlayerGear:
        return PlayerGear(
            id=model.id,
            player_id=model.player_id,
            item_definition=map_item_definition(model.item_definition),
            rarity=model.rarity,
            forge_level=int(model.forge_level or 0),
            equipped_slot=model.equipped_slot,
            source=model.source or "drop",
            created_at=model.created_at,
            listed=bool(model.listed),
        )
