"""File de commandes admin web → bot (cf. AdminCommandModel)."""

from __future__ import annotations

import json
from datetime import datetime, UTC

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.infrastructure.db.models.admin_command_model import AdminCommandModel

# Actions reconnues par le pont (le bot refuse tout le reste).
KNOWN_ACTIONS = (
    "spawn_encounter",   # {mob_code?, element?, channel_id?}
    "stop_encounter",    # {}
    "resolve_encounter",  # {} — force la résolution du combat en cours
    "spawn_boss",        # {boss_code}
    "stop_boss",         # {}
    "spawn_event",       # {event_type}
)


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class AdminCommandRepository:
    def __init__(self, session: Session):
        self.session = session

    def enqueue(
        self, action: str, payload: dict | None = None, requested_by: int = 0
    ) -> AdminCommandModel:
        cmd = AdminCommandModel(
            action=action,
            payload_json=json.dumps(payload or {}),
            requested_by=requested_by,
        )
        self.session.add(cmd)
        self.session.flush()
        return cmd

    def list_pending(self, limit: int = 20) -> list[AdminCommandModel]:
        stmt = (
            select(AdminCommandModel)
            .where(AdminCommandModel.status == "pending")
            .order_by(AdminCommandModel.created_at.asc())
            .limit(limit)
        )
        return list(self.session.execute(stmt).scalars().all())

    def list_recent(self, limit: int = 15) -> list[AdminCommandModel]:
        stmt = (
            select(AdminCommandModel)
            .order_by(AdminCommandModel.created_at.desc())
            .limit(limit)
        )
        return list(self.session.execute(stmt).scalars().all())

    def mark(self, command_id: int, status: str, result: str = "") -> None:
        cmd = self.session.get(AdminCommandModel, command_id)
        if cmd is None:
            return
        cmd.status = status
        cmd.result = (result or "")[:500]
        cmd.attempts += 1
        cmd.executed_at = _now()
        self.session.flush()
