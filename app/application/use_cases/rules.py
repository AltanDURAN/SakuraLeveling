"""Règlement : qui l'a accepté, et quelle version (07/11/2026).

Texte : `rules.json` ; règles pures : `app/domain/services/rules_service.py`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.services.monitoring import kinds
from app.infrastructure.db.models.player_model import PlayerModel
from app.infrastructure.db.models.rules_model import RulesAcceptanceModel
from app.infrastructure.db.unit_of_work import atomic
from app.infrastructure.monitoring.telemetry import record as record_event


@dataclass(frozen=True)
class Acceptance:
    version: int
    accepted_at: datetime


def acceptance(session: Session, discord_id: int) -> Acceptance | None:
    row = session.get(RulesAcceptanceModel, discord_id)
    return None if row is None else Acceptance(row.version, row.accepted_at)


def accept(session: Session, discord_id: int, version: int) -> bool:
    """Retient que ce compte accepte cette version. Renvoie False s'il
    l'avait déjà acceptée (rien ne change : la date reste la première)."""
    with atomic(session):
        row = session.get(RulesAcceptanceModel, discord_id)
        if row is not None and row.version >= version:
            return False
        now = datetime.now(UTC).replace(tzinfo=None)
        if row is None:
            session.add(RulesAcceptanceModel(discord_id=discord_id, version=version, accepted_at=now))
        else:
            row.version, row.accepted_at = version, now
        player_id = session.execute(
            select(PlayerModel.id).where(PlayerModel.discord_id == discord_id)).scalar_one_or_none()
        record_event(session, kinds.RULES, discord_id=discord_id, player_id=player_id, qty=version)
        return True
