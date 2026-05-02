"""Repository pour les assignations de quêtes quotidiennes."""

from datetime import datetime, UTC

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.infrastructure.db.models.daily_quest_model import DailyQuestAssignmentModel


class DailyQuestRepository:
    def __init__(self, session: Session):
        self.session = session

    def list_for_player_day(
        self, player_id: int, day_start: datetime
    ) -> list[DailyQuestAssignmentModel]:
        stmt = select(DailyQuestAssignmentModel).where(
            DailyQuestAssignmentModel.player_id == player_id,
            DailyQuestAssignmentModel.day_start == day_start,
        )
        return list(self.session.execute(stmt).scalars().all())

    def has_assignments_for_day(
        self, player_id: int, day_start: datetime
    ) -> bool:
        return len(self.list_for_player_day(player_id, day_start)) > 0

    def assign(
        self, player_id: int, day_start: datetime, quest_codes: list[str]
    ) -> None:
        now = datetime.now(UTC)
        for code in quest_codes:
            self.session.add(
                DailyQuestAssignmentModel(
                    player_id=player_id,
                    day_start=day_start,
                    quest_code=code,
                    progress=0,
                    completed=False,
                    claimed=False,
                    created_at=now,
                    updated_at=now,
                )
            )
        self.session.commit()

    def get_assignment(
        self, player_id: int, day_start: datetime, quest_code: str
    ) -> DailyQuestAssignmentModel | None:
        stmt = select(DailyQuestAssignmentModel).where(
            DailyQuestAssignmentModel.player_id == player_id,
            DailyQuestAssignmentModel.day_start == day_start,
            DailyQuestAssignmentModel.quest_code == quest_code,
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def add_progress(
        self,
        player_id: int,
        day_start: datetime,
        quest_code: str,
        amount: int,
        objective_quantity: int,
    ) -> tuple[DailyQuestAssignmentModel | None, bool]:
        """Incrémente. Retourne (assignment, just_completed).
        `just_completed=True` si CET appel vient de la marquer completed."""
        model = self.get_assignment(player_id, day_start, quest_code)
        if model is None or model.completed:
            return model, False
        model.progress += amount
        just_completed = False
        if model.progress >= objective_quantity:
            model.progress = objective_quantity
            model.completed = True
            just_completed = True
        model.updated_at = datetime.now(UTC)
        self.session.commit()
        return model, just_completed

    def set_progress_at_least(
        self,
        player_id: int,
        day_start: datetime,
        quest_code: str,
        value: int,
        objective_quantity: int,
    ) -> tuple[DailyQuestAssignmentModel | None, bool]:
        model = self.get_assignment(player_id, day_start, quest_code)
        if model is None or model.completed:
            return model, False
        just_completed = False
        if value > model.progress:
            model.progress = min(value, objective_quantity)
            if model.progress >= objective_quantity:
                model.completed = True
                just_completed = True
            model.updated_at = datetime.now(UTC)
            self.session.commit()
        return model, just_completed

    def mark_claimed(
        self, player_id: int, day_start: datetime, quest_code: str
    ) -> bool:
        model = self.get_assignment(player_id, day_start, quest_code)
        if model is None or not model.completed or model.claimed:
            return False
        model.claimed = True
        model.updated_at = datetime.now(UTC)
        self.session.commit()
        return True

    def delete_for_player(self, player_id: int) -> None:
        from sqlalchemy import delete
        self.session.execute(
            delete(DailyQuestAssignmentModel).where(
                DailyQuestAssignmentModel.player_id == player_id
            )
        )
        self.session.commit()
