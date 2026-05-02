"""Repository pour les assignations de quêtes hebdomadaires."""

from datetime import datetime, UTC

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.infrastructure.db.models.weekly_quest_model import WeeklyQuestAssignmentModel


class WeeklyQuestRepository:
    def __init__(self, session: Session):
        self.session = session

    def list_for_player_week(
        self, player_id: int, week_start: datetime
    ) -> list[WeeklyQuestAssignmentModel]:
        stmt = select(WeeklyQuestAssignmentModel).where(
            WeeklyQuestAssignmentModel.player_id == player_id,
            WeeklyQuestAssignmentModel.week_start == week_start,
        )
        return list(self.session.execute(stmt).scalars().all())

    def has_assignments_for_week(
        self, player_id: int, week_start: datetime
    ) -> bool:
        return len(self.list_for_player_week(player_id, week_start)) > 0

    def assign(
        self, player_id: int, week_start: datetime, quest_codes: list[str]
    ) -> None:
        now = datetime.now(UTC)
        for code in quest_codes:
            self.session.add(
                WeeklyQuestAssignmentModel(
                    player_id=player_id,
                    week_start=week_start,
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
        self, player_id: int, week_start: datetime, quest_code: str
    ) -> WeeklyQuestAssignmentModel | None:
        stmt = select(WeeklyQuestAssignmentModel).where(
            WeeklyQuestAssignmentModel.player_id == player_id,
            WeeklyQuestAssignmentModel.week_start == week_start,
            WeeklyQuestAssignmentModel.quest_code == quest_code,
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def add_progress(
        self,
        player_id: int,
        week_start: datetime,
        quest_code: str,
        amount: int,
        objective_quantity: int,
    ) -> WeeklyQuestAssignmentModel | None:
        """Incrémente la progression et marque completed si seuil atteint."""
        model = self.get_assignment(player_id, week_start, quest_code)
        if model is None or model.completed:
            return model
        model.progress += amount
        if model.progress >= objective_quantity:
            model.progress = objective_quantity
            model.completed = True
        model.updated_at = datetime.now(UTC)
        self.session.commit()
        return model

    def set_progress_at_least(
        self,
        player_id: int,
        week_start: datetime,
        quest_code: str,
        value: int,
        objective_quantity: int,
    ) -> WeeklyQuestAssignmentModel | None:
        """Pour les objectifs "atteindre la valeur N" plutôt qu'incrémenter
        (ex : daily_streak)."""
        model = self.get_assignment(player_id, week_start, quest_code)
        if model is None or model.completed:
            return model
        if value > model.progress:
            model.progress = min(value, objective_quantity)
            if model.progress >= objective_quantity:
                model.completed = True
            model.updated_at = datetime.now(UTC)
            self.session.commit()
        return model

    def mark_claimed(
        self, player_id: int, week_start: datetime, quest_code: str
    ) -> bool:
        model = self.get_assignment(player_id, week_start, quest_code)
        if model is None or not model.completed or model.claimed:
            return False
        model.claimed = True
        model.updated_at = datetime.now(UTC)
        self.session.commit()
        return True

    def delete_for_player(self, player_id: int) -> None:
        from sqlalchemy import delete
        self.session.execute(
            delete(WeeklyQuestAssignmentModel).where(
                WeeklyQuestAssignmentModel.player_id == player_id
            )
        )
        self.session.commit()
