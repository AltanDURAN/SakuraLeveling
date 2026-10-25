"""Repository des assignations de quêtes hebdomadaires."""

from app.infrastructure.db.models.weekly_quest_model import WeeklyQuestAssignmentModel
from app.infrastructure.db.repositories.quest_assignment_repository import (
    QuestAssignmentRepository,
)


class WeeklyQuestRepository(QuestAssignmentRepository):
    model = WeeklyQuestAssignmentModel
    period_column = "week_start"

    def list_for_player_week(self, player_id, week_start):
        return self.list_for_player(player_id, week_start)

    def has_assignments_for_week(self, player_id, week_start) -> bool:
        return self.has_assignments(player_id, week_start)
