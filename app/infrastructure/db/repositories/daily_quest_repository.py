"""Repository des assignations de quêtes quotidiennes."""

from app.infrastructure.db.models.daily_quest_model import DailyQuestAssignmentModel
from app.infrastructure.db.repositories.quest_assignment_repository import (
    QuestAssignmentRepository,
)


class DailyQuestRepository(QuestAssignmentRepository):
    model = DailyQuestAssignmentModel
    period_column = "day_start"
