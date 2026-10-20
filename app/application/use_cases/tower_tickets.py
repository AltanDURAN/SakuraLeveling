"""Tickets d'entrée de la tour solo (la tour elle-même viendra plus tard).

Chaque jour (UTC), un joueur a un quota de tickets : 1 de base, +1 s'il a monté
la case « Confort » qui donne le ticket bonus. Les tickets ne s'accumulent
PAS : un ticket non utilisé est perdu à minuit, le lendemain on repart du
quota (1 bonus maximum par jour, jamais 2).

La future tour appellera `consume()` avant de lancer une tentative.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, UTC

from sqlalchemy.orm import Session

from app.domain.services.skill_tree_service import SkillTreeService
from app.infrastructure.db.models.tower_ticket_model import PlayerTowerTicketModel
from app.infrastructure.db.repositories.player_skill_allocation_repository import (
    PlayerSkillAllocationRepository,
)
from app.infrastructure.skill_tree.skill_tree_loader import get_definition

BASE_DAILY_TICKETS = 1
BONUS_FEATURE = "tower_bonus_ticket"


@dataclass(frozen=True)
class TicketStatus:
    available: int
    allowance: int
    has_bonus: bool


def daily_allowance(features: set[str]) -> int:
    return BASE_DAILY_TICKETS + (1 if BONUS_FEATURE in features else 0)


class TowerTicketsUseCase:
    def __init__(self, session: Session) -> None:
        self.session = session

    def _today(self, now: datetime | None = None) -> date:
        return (now or datetime.now(UTC)).astimezone(UTC).date()

    def _features(self, player_id: int) -> set[str]:
        allocations = PlayerSkillAllocationRepository(self.session).list_by_player(player_id)
        return SkillTreeService(get_definition()).unlocked_features(allocations)

    def _used_today(self, player_id: int, today: date) -> int:
        row = self.session.get(PlayerTowerTicketModel, player_id)
        return row.used if row is not None and row.day == today else 0

    def status(self, player_id: int, now: datetime | None = None) -> TicketStatus:
        features = self._features(player_id)
        allowance = daily_allowance(features)
        used = self._used_today(player_id, self._today(now))
        return TicketStatus(
            available=max(0, allowance - used),
            allowance=allowance,
            has_bonus=BONUS_FEATURE in features,
        )

    def consume(self, player_id: int, now: datetime | None = None) -> bool:
        """Utilise un ticket du jour. False s'il n'en reste plus."""
        today = self._today(now)
        if self.status(player_id, now).available <= 0:
            return False
        row = self.session.get(PlayerTowerTicketModel, player_id)
        if row is None:
            self.session.add(PlayerTowerTicketModel(player_id=player_id, day=today, used=1))
        elif row.day != today:
            row.day, row.used = today, 1
        else:
            row.used += 1
        self.session.flush()
        return True
