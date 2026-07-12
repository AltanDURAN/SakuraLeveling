from datetime import datetime, UTC

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.entities.player_mana_state import PlayerManaState
from app.infrastructure.db.models.player_mana_state_model import PlayerManaStateModel


class PlayerManaRepository:
    """Lecture/écriture du mana courant (miroir de PlayerHealthRepository)."""

    def __init__(self, session: Session):
        self.session = session

    def get_by_player_id(self, player_id: int) -> PlayerManaState | None:
        stmt = select(PlayerManaStateModel).where(
            PlayerManaStateModel.player_id == player_id
        )
        model = self.session.execute(stmt).scalar_one_or_none()

        if model is None:
            return None

        return PlayerManaState(
            player_id=model.player_id,
            current_mana=model.current_mana,
            updated_at=model.updated_at,
        )

    def create(self, player_id: int, current_mana: int) -> PlayerManaState:
        model = PlayerManaStateModel(
            player_id=player_id,
            current_mana=current_mana,
            updated_at=datetime.now(UTC),
        )

        self.session.add(model)
        self.session.commit()
        self.session.refresh(model)

        return PlayerManaState(
            player_id=model.player_id,
            current_mana=model.current_mana,
            updated_at=model.updated_at,
        )

    def get_or_create(self, player_id: int, default_current_mana: int) -> PlayerManaState:
        existing = self.get_by_player_id(player_id)
        if existing is not None:
            return existing

        return self.create(player_id=player_id, current_mana=default_current_mana)

    def update_current_mana(self, player_id: int, current_mana: int) -> None:
        stmt = select(PlayerManaStateModel).where(
            PlayerManaStateModel.player_id == player_id
        )
        model = self.session.execute(stmt).scalar_one_or_none()

        if model is None:
            return

        model.current_mana = current_mana
        model.updated_at = datetime.now(UTC)
        self.session.commit()

    def refresh_current_mana(
        self,
        player_id: int,
        new_current_mana: int,
    ) -> PlayerManaState | None:
        stmt = select(PlayerManaStateModel).where(
            PlayerManaStateModel.player_id == player_id
        )
        model = self.session.execute(stmt).scalar_one_or_none()

        if model is None:
            return None

        model.current_mana = new_current_mana
        model.updated_at = datetime.now(UTC)
        self.session.commit()
        self.session.refresh(model)

        return PlayerManaState(
            player_id=model.player_id,
            current_mana=model.current_mana,
            updated_at=model.updated_at,
        )
