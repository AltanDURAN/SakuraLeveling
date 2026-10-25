"""Repository des assignations de quêtes quotidiennes."""

from app.infrastructure.db.models.daily_quest_model import DailyQuestAssignmentModel
from app.infrastructure.db.repositories.quest_assignment_repository import (
    QuestAssignmentRepository,
)


class DailyQuestRepository(QuestAssignmentRepository):
    model = DailyQuestAssignmentModel
    period_column = "day_start"

    def list_for_player_day(self, player_id, day_start):
        return self.list_for_player(player_id, day_start)

    def has_assignments_for_day(self, player_id, day_start) -> bool:
        return self.has_assignments(player_id, day_start)
