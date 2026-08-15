"""Repository des instances d'événements non-combat + état du scheduler.

Instances en DB (comme world boss) : permet la résolution différée (5 min) et
la survie au reboot. Le coffre utilise un claim ATOMIQUE du gagnant (premier
arrivé) via UPDATE ... WHERE winner IS NULL.
"""

from __future__ import annotations

import json
from datetime import datetime, UTC

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.infrastructure.db.models.event_model import (
    ActiveEventModel,
    EventParticipationModel,
    EventSchedulerStateModel,
)

GLOBAL_KEY = "__global__"


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class EventRepository:
    def __init__(self, session: Session):
        self.session = session

    # ---------- instances ----------

    def create(
        self,
        event_type: str,
        channel_id: int,
        expires_at: datetime | None = None,
        payload: dict | None = None,
    ) -> ActiveEventModel:
        ev = ActiveEventModel(
            event_type=event_type,
            channel_id=channel_id,
            status="active",
            payload_json=json.dumps(payload or {}),
            expires_at=expires_at,
        )
        self.session.add(ev)
        self.session.flush()
        return ev

    def get_by_id(self, event_id: int) -> ActiveEventModel | None:
        return self.session.get(ActiveEventModel, event_id)

    def get_active_by_type(self, event_type: str) -> ActiveEventModel | None:
        stmt = (
            select(ActiveEventModel)
            .where(
                ActiveEventModel.event_type == event_type,
                ActiveEventModel.status == "active",
            )
            .order_by(ActiveEventModel.created_at.desc())
            .limit(1)
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def set_message_id(self, event_id: int, message_id: int) -> None:
        self.session.execute(
            update(ActiveEventModel)
            .where(ActiveEventModel.id == event_id)
            .values(message_id=message_id)
        )

    def set_status(self, event_id: int, status: str) -> None:
        self.session.execute(
            update(ActiveEventModel)
            .where(ActiveEventModel.id == event_id)
            .values(status=status)
        )

    def set_payload(self, event_id: int, payload: dict) -> None:
        self.session.execute(
            update(ActiveEventModel)
            .where(ActiveEventModel.id == event_id)
            .values(payload_json=json.dumps(payload or {}))
        )

    def list_due(self, event_type: str | None = None) -> list[ActiveEventModel]:
        """Événements actifs dont l'échéance est passée (résolution différée)."""
        conds = [
            ActiveEventModel.status == "active",
            ActiveEventModel.expires_at.is_not(None),
            ActiveEventModel.expires_at <= _now(),
        ]
        if event_type:
            conds.append(ActiveEventModel.event_type == event_type)
        stmt = select(ActiveEventModel).where(*conds)
        return list(self.session.execute(stmt).scalars().all())

    def claim_chest_winner(self, event_id: int, player_id: int) -> bool:
        """Claim ATOMIQUE : n'attribue le gagnant que si personne ne l'a fait.
        Retourne True si CE joueur vient de gagner."""
        result = self.session.execute(
            update(ActiveEventModel)
            .where(
                ActiveEventModel.id == event_id,
                ActiveEventModel.status == "active",
                ActiveEventModel.winner_player_id.is_(None),
            )
            .values(winner_player_id=player_id, status="resolved")
        )
        self.session.commit()
        return (result.rowcount or 0) == 1

    # ---------- participations ----------

    def upsert_participation(
        self,
        event_id: int,
        player_id: int,
        choice: str = "",
        payload: dict | None = None,
    ) -> EventParticipationModel:
        stmt = select(EventParticipationModel).where(
            EventParticipationModel.event_id == event_id,
            EventParticipationModel.player_id == player_id,
        )
        row = self.session.execute(stmt).scalar_one_or_none()
        if row is None:
            row = EventParticipationModel(
                event_id=event_id,
                player_id=player_id,
                choice=choice,
                payload_json=json.dumps(payload or {}),
            )
            self.session.add(row)
        else:
            row.choice = choice
            if payload is not None:
                row.payload_json = json.dumps(payload)
            row.updated_at = _now()
        self.session.flush()
        return row

    def get_participation(
        self, event_id: int, player_id: int
    ) -> EventParticipationModel | None:
        stmt = select(EventParticipationModel).where(
            EventParticipationModel.event_id == event_id,
            EventParticipationModel.player_id == player_id,
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def list_participations(self, event_id: int) -> list[EventParticipationModel]:
        stmt = select(EventParticipationModel).where(
            EventParticipationModel.event_id == event_id
        )
        return list(self.session.execute(stmt).scalars().all())

    # ---------- scheduler ----------

    def get_last_spawn(self, key: str) -> datetime | None:
        row = self.session.get(EventSchedulerStateModel, key)
        return row.last_spawn_at if row else None

    def touch_spawn(self, event_type: str, when: datetime | None = None) -> None:
        """Met à jour last_spawn pour le type ET la ligne globale (espacement 1h)."""
        when = when or _now()
        for key in (event_type, GLOBAL_KEY):
            row = self.session.get(EventSchedulerStateModel, key)
            if row is None:
                row = EventSchedulerStateModel(event_type=key, last_spawn_at=when)
                self.session.add(row)
            else:
                row.last_spawn_at = when
        self.session.flush()
