"""Épreuves de rôle : meilleurs scores du jour et clôture des semaines."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.infrastructure.db.models.role_trial_model import RoleTrialScoreModel, RoleTrialWeekModel


class RoleTrialRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def record(self, player_id: int, day: date, role: str, variant_code: str,
               score: int) -> tuple[int, bool, int]:
        """Enregistre un essai. Renvoie (meilleur score du jour, nouveau
        record ?, nombre d'essais du jour)."""
        row = self.session.execute(
            select(RoleTrialScoreModel).where(
                RoleTrialScoreModel.player_id == player_id,
                RoleTrialScoreModel.day == day,
                RoleTrialScoreModel.role == role,
            )
        ).scalar_one_or_none()
        if row is None:
            row = RoleTrialScoreModel(player_id=player_id, day=day, role=role,
                                      variant_code=variant_code, score=score, attempts=1,
                                      updated_at=datetime.now(UTC))
            self.session.add(row)
            self.session.flush()
            return score, True, 1
        row.attempts = (row.attempts or 0) + 1
        improved = score > (row.score or 0)
        if improved:
            row.score = score
            row.updated_at = datetime.now(UTC)
        self.session.flush()
        return row.score, improved, row.attempts

    def day_scores(self, day: date, role: str) -> list[tuple[int, int]]:
        """(player_id, score) du jour pour ce rôle, du meilleur au moins bon."""
        rows = self.session.execute(
            select(RoleTrialScoreModel.player_id, RoleTrialScoreModel.score)
            .where(RoleTrialScoreModel.day == day, RoleTrialScoreModel.role == role)
            .order_by(RoleTrialScoreModel.score.desc(), RoleTrialScoreModel.player_id)
        ).all()
        return [(pid, score) for pid, score in rows]

    def player_day(self, player_id: int, day: date) -> dict[str, tuple[int, int]]:
        """{rôle: (meilleur score, essais)} du joueur ce jour-là."""
        rows = self.session.execute(
            select(RoleTrialScoreModel).where(
                RoleTrialScoreModel.player_id == player_id, RoleTrialScoreModel.day == day)
        ).scalars().all()
        return {r.role: (r.score, r.attempts) for r in rows}

    def week_rows(self, first_day: date, last_day: date) -> list[tuple[int, str, date, int]]:
        """(player_id, rôle, jour, meilleur score) entre deux jours inclus."""
        rows = self.session.execute(
            select(RoleTrialScoreModel.player_id, RoleTrialScoreModel.role,
                   RoleTrialScoreModel.day, RoleTrialScoreModel.score)
            .where(RoleTrialScoreModel.day >= first_day, RoleTrialScoreModel.day <= last_day)
        ).all()
        return [tuple(r) for r in rows]

    def is_settled(self, week_start: date) -> bool:
        return self.session.get(RoleTrialWeekModel, week_start) is not None

    def mark_settled(self, week_start: date, results: dict) -> None:
        self.session.add(RoleTrialWeekModel(
            week_start=week_start, settled_at=datetime.now(UTC),
            results_json=json.dumps(results, ensure_ascii=False)))
        self.session.flush()

    def delete_for_player(self, player_id: int) -> None:
        for row in self.session.execute(
            select(RoleTrialScoreModel).where(RoleTrialScoreModel.player_id == player_id)
        ).scalars():
            self.session.delete(row)
