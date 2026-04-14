from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.entities.player_health_state import PlayerHealthState
from app.infrastructure.db.models.player_health_state_model import PlayerHealthStateModel


class PlayerHealthRepository:
    def __init__(self, session: Session):
        self.session = session

    def get_by_player_id(self, player_id: int) -> PlayerHealthState | None:
        stmt = select(PlayerHealthStateModel).where(
            PlayerHealthStateModel.player_id == player_id
        )
        model = self.session.execute(stmt).scalar_one_or_none()

        if model is None:
            return None

        return PlayerHealthState(
            player_id=model.player_id,
            current_hp=model.current_hp,
            updated_at=model.updated_at,
        )

    def create(self, player_id: int, current_hp: int) -> PlayerHealthState:
        model = PlayerHealthStateModel(
            player_id=player_id,
            current_hp=current_hp,
            updated_at=datetime.now(timezone.utc),
        )

        self.session.add(model)
        self.session.commit()
        self.session.refresh(model)

        return PlayerHealthState(
            player_id=model.player_id,
            current_hp=model.current_hp,
            updated_at=model.updated_at,
        )

    def get_or_create(self, player_id: int, default_current_hp: int) -> PlayerHealthState:
        existing = self.get_by_player_id(player_id)
        if existing is not None:
            return existing

        return self.create(player_id=player_id, current_hp=default_current_hp)

    def update_current_hp(self, player_id: int, current_hp: int) -> None:
        stmt = select(PlayerHealthStateModel).where(
            PlayerHealthStateModel.player_id == player_id
        )
        model = self.session.execute(stmt).scalar_one_or_none()

        if model is None:
            return

        model.current_hp = current_hp
        model.updated_at = datetime.now(timezone.utc)
        self.session.commit()
        
    def refresh_current_hp(
        self,
        player_id: int,
        new_current_hp: int,
    ) -> PlayerHealthState | None:
        stmt = select(PlayerHealthStateModel).where(
            PlayerHealthStateModel.player_id == player_id
        )
        model = self.session.execute(stmt).scalar_one_or_none()

        if model is None:
            return None

        model.current_hp = new_current_hp
        model.updated_at = datetime.now(timezone.utc)
        self.session.commit()
        self.session.refresh(model)

        return PlayerHealthState(
            player_id=model.player_id,
            current_hp=model.current_hp,
            updated_at=model.updated_at,
        )