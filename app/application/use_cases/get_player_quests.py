from app.infrastructure.db.repositories.inventory_repository import InventoryRepository
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.repositories.quest_repository import QuestRepository
from app.domain.services.quest_service import QuestService


class GetPlayerQuestsUseCase:
    def __init__(
        self,
        player_repository: PlayerRepository,
        quest_repository: QuestRepository,
        inventory_repository: InventoryRepository,
        quest_service: QuestService,
    ):
        self.player_repository = player_repository
        self.quest_repository = quest_repository
        self.inventory_repository = inventory_repository
        self.quest_service = quest_service

    def execute(
        self,
        discord_id: int,
        username: str,
        display_name: str,
    ) -> list[dict]:
        profile = self.player_repository.get_or_create_by_discord_id(
            discord_id=discord_id,
            username=username,
            display_name=display_name,
        )

        quests = self.quest_repository.list_definitions()
        inventory_items = self.inventory_repository.list_by_player_id(profile.player.id)

        results: list[dict] = []

        for quest in quests:
            state = self.quest_repository.get_or_create_player_quest_state(
                profile.player.id,
                quest.id,
            )

            progress = state.progress_quantity
            is_completed = state.is_completed

            if quest.objective_type == "collect_item":
                progress, is_completed = self.quest_service.compute_progress_for_collect_quest(
                    quest,
                    inventory_items,
                )
                self.quest_repository.update_progress(
                    profile.player.id,
                    quest.id,
                    progress,
                    is_completed,
                )

            results.append(
                {
                    "quest": quest,
                    "state": state,
                    "progress": progress,
                    "is_completed": is_completed,
                }
            )

        return results