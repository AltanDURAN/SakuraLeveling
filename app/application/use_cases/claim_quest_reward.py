from app.domain.services.progression_service import ProgressionService
from app.infrastructure.db.repositories.inventory_repository import InventoryRepository
from app.infrastructure.db.repositories.item_repository import ItemRepository
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.repositories.quest_repository import QuestRepository


class ClaimQuestRewardUseCase:
    def __init__(
        self,
        player_repository: PlayerRepository,
        quest_repository: QuestRepository,
        item_repository: ItemRepository,
        inventory_repository: InventoryRepository,
        progression_service: ProgressionService,
    ):
        self.player_repository = player_repository
        self.quest_repository = quest_repository
        self.item_repository = item_repository
        self.inventory_repository = inventory_repository
        self.progression_service = progression_service

    def execute(
        self,
        discord_id: int,
        username: str,
        display_name: str,
        quest_code: str,
    ) -> tuple[bool, str]:
        profile = self.player_repository.get_or_create_by_discord_id(
            discord_id=discord_id,
            username=username,
            display_name=display_name,
        )

        quest = self.quest_repository.get_definition_by_code(quest_code)
        if quest is None:
            return False, "Quête introuvable."

        state = self.quest_repository.get_or_create_player_quest_state(
            profile.player.id,
            quest.id,
        )

        if state.is_claimed:
            return False, "Récompense déjà récupérée."

        if not state.is_completed:
            return False, "Quête non terminée."

        self.player_repository.add_gold(profile.player.id, quest.reward_gold)

        new_level, new_xp, new_skill_points = self.progression_service.apply_level_up(
            current_level=profile.progression.level,
            current_xp=profile.progression.xp,
            gained_xp=quest.reward_xp,
            current_skill_points=profile.progression.skill_points,
        )

        self.player_repository.apply_progression(
            player_id=profile.player.id,
            new_level=new_level,
            new_xp=new_xp,
            new_skill_points=new_skill_points,
        )

        for reward_item in quest.reward_items or []:
            item = self.item_repository.get_by_code(reward_item["item_code"])
            if item is None:
                continue

            self.inventory_repository.add_item(
                player_id=profile.player.id,
                item_definition_id=item.id,
                quantity=reward_item["quantity"],
            )

        self.quest_repository.mark_claimed(profile.player.id, quest.id)

        return True, f"Récompense de quête `{quest_code}` récupérée."