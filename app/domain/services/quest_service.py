from app.domain.entities.player_inventory_item import PlayerInventoryItem
from app.domain.entities.quest_definition import QuestDefinition


class QuestService:
    def compute_progress_for_collect_quest(
        self,
        quest: QuestDefinition,
        inventory_items: list[PlayerInventoryItem],
    ) -> tuple[int, bool]:
        total_quantity = 0

        for item in inventory_items:
            if item.item_definition.code == quest.target_code:
                total_quantity += item.quantity

        progress = min(total_quantity, quest.required_quantity)
        is_completed = progress >= quest.required_quantity
        return progress, is_completed

    def compute_progress_for_kill_quest(
        self,
        quest: QuestDefinition,
        current_progress: int,
        killed_mob_code: str | None,
    ) -> tuple[int, bool]:
        if killed_mob_code == quest.target_code:
            current_progress += 1

        progress = min(current_progress, quest.required_quantity)
        is_completed = progress >= quest.required_quantity
        return progress, is_completed