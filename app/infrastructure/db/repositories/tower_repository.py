"""Progression de la tour solo (`player_tower_progress`)."""

from __future__ import annotations

from datetime import date, datetime, UTC

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.infrastructure.db.models.player_model import PlayerModel
from app.infrastructure.db.models.tower_progress_model import PlayerTowerProgressModel


class TowerRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_or_create(self, player_id: int) -> PlayerTowerProgressModel:
        row = self.session.get(PlayerTowerProgressModel, player_id)
        if row is None:
            row = PlayerTowerProgressModel(player_id=player_id, best_floor=0, attempts=0, wins=0)
            self.session.add(row)
            self.session.flush()
        return row

    def best_floor(self, player_id: int) -> int:
        row = self.session.get(PlayerTowerProgressModel, player_id)
        return row.best_floor if row is not None else 0

    def record_attempt(self, player_id: int, floor: int, victory: bool) -> PlayerTowerProgressModel:
        """Un essai sur `floor` ; une victoire sur l'étage suivant le record
        le fait avancer (jamais reculer)."""
        row = self.get_or_create(player_id)
        row.attempts += 1
        if victory:
            row.wins += 1
            if floor > row.best_floor:
                row.best_floor = floor
                row.best_at = datetime.now(UTC).replace(tzinfo=None)
        self.session.flush()
        return row

    def set_best_floor(self, player_id: int, floor: int) -> None:
        """Admin : fixe le record (tests)."""
        row = self.get_or_create(player_id)
        row.best_floor = max(0, floor)
        row.best_at = datetime.now(UTC).replace(tzinfo=None)
        self.session.flush()

    def claim_daily(self, player_id: int, day: date) -> bool:
        """Marque la récompense du jour comme prise. False si déjà prise."""
        row = self.get_or_create(player_id)
        if row.daily_claimed_on == day:
            return False
        row.daily_claimed_on = day
        self.session.flush()
        return True

    def leaderboard(self, limit: int = 10) -> list[tuple[int, int, str]]:
        """[(player_id, étage record, nom)] — record le plus haut d'abord, le
        premier arrivé à égalité."""
        rows = self.session.execute(
            select(PlayerTowerProgressModel.player_id, PlayerTowerProgressModel.best_floor,
                   PlayerModel.display_name)
            .join(PlayerModel, PlayerModel.id == PlayerTowerProgressModel.player_id)
            .where(PlayerTowerProgressModel.best_floor > 0)
            .order_by(PlayerTowerProgressModel.best_floor.desc(), PlayerTowerProgressModel.best_at.asc())
            .limit(limit)
        ).all()
        return [(pid, floor, name) for pid, floor, name in rows]
