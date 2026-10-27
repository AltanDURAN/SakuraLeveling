from datetime import datetime, UTC

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.value_objects.cooldown import Cooldown
from app.infrastructure.db.models.cooldown_model import PlayerCooldownModel
from app.infrastructure.db.unit_of_work import commit


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

    def list_for_player(self, player_id: int) -> list[Cooldown]:
        """Tous les cooldowns d'un joueur (actifs ET passés)."""
        stmt = select(PlayerCooldownModel).where(
            PlayerCooldownModel.player_id == player_id,
        ).order_by(PlayerCooldownModel.action_key.asc())
        return [
            self._to_domain(m)
            for m in self.session.execute(stmt).scalars().all()
        ]

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
        now = datetime.now(UTC)

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

        commit(self.session)

    def _to_domain(self, model: PlayerCooldownModel) -> Cooldown:
        return Cooldown(
            player_id=model.player_id,
            action_key=model.action_key,
            last_used_at=model.last_used_at,
            next_available_at=model.next_available_at,
        )

    def list_due_unnotified(
        self, now: datetime, since: datetime, action_keys: set[str],
    ) -> list[tuple[int, int, str, datetime]]:
        """Cooldowns échus entre `since` et `now` dont le joueur n'a pas encore
        été prévenu : (id, player_id, action_key, next_available_at)."""
        stmt = select(PlayerCooldownModel).where(
            PlayerCooldownModel.action_key.in_(list(action_keys)),
            PlayerCooldownModel.next_available_at.is_not(None),
            PlayerCooldownModel.next_available_at <= now.replace(tzinfo=None),
            PlayerCooldownModel.next_available_at >= since.replace(tzinfo=None),
        )
        out = []
        for model in self.session.execute(stmt).scalars().all():
            if model.notified_for != model.next_available_at:
                out.append((model.id, model.player_id, model.action_key, model.next_available_at))
        return out

    def mark_notified(self, cooldown_id: int, next_available_at: datetime) -> None:
        model = self.session.get(PlayerCooldownModel, cooldown_id)
        if model is not None:
            model.notified_for = next_available_at
