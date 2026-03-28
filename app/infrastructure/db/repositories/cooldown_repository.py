from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.value_objects.cooldown import Cooldown
from app.infrastructure.db.models.cooldown_model import PlayerCooldownModel


class CooldownRepository:
    def __init__(self, session: Session):
        self.session = session

    def get_by_player_and_action(self, player_id: int, action_key: str) -> Cooldown | None:
        stmt = select(PlayerCooldownModel).where(
            PlayerCooldownModel.player_id == player_id,
            PlayerCooldownModel.action_key == action_key,
        )
        model = self.session.execute(stmt).scalar_one_or_none()

        if model is None:
            return None

        return self._to_domain(model)

    def upsert(
        self,
        player_id: int,
        action_key: str,
        last_used_at: datetime,
        next_available_at: datetime,
    ) -> None:
        stmt = select(PlayerCooldownModel).where(
            PlayerCooldownModel.player_id == player_id,
            PlayerCooldownModel.action_key == action_key,
        )
        model = self.session.execute(stmt).scalar_one_or_none()
        now = datetime.utcnow()

        if model is None:
            model = PlayerCooldownModel(
                player_id=player_id,
                action_key=action_key,
                last_used_at=last_used_at,
                next_available_at=next_available_at,
                created_at=now,
                updated_at=now,
            )
            self.session.add(model)
        else:
            model.last_used_at = last_used_at
            model.next_available_at = next_available_at
            model.updated_at = now

        self.session.commit()

    def _to_domain(self, model: PlayerCooldownModel) -> Cooldown:
        return Cooldown(
            player_id=model.player_id,
            action_key=model.action_key,
            last_used_at=model.last_used_at,
            next_available_at=model.next_available_at,
        )