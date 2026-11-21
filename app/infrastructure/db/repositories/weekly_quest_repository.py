"""Repository des assignations de quêtes hebdomadaires."""

from app.infrastructure.db.models.weekly_quest_model import WeeklyQuestAssignmentModel
from app.infrastructure.db.repositories.quest_assignment_repository import (
    QuestAssignmentRepository,
)


class WeeklyQuestRepository(QuestAssignmentRepository):
    model = WeeklyQuestAssignmentModel
    period_column = "week_start"
