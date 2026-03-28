from app.domain.services.craft_service import CraftService
from app.infrastructure.db.repositories.craft_repository import CraftRepository
from app.infrastructure.db.repositories.inventory_repository import InventoryRepository
from app.infrastructure.db.repositories.item_repository import ItemRepository
from app.infrastructure.db.repositories.player_repository import PlayerRepository


class CraftItemUseCase:
    def __init__(
        self,
        player_repository: PlayerRepository,
        craft_repository: CraftRepository,
        inventory_repository: InventoryRepository,
        item_repository: ItemRepository,
        craft_service: CraftService,
    ):
        self.player_repository = player_repository
        self.craft_repository = craft_repository
        self.inventory_repository = inventory_repository
        self.item_repository = item_repository
        self.craft_service = craft_service

    def execute(
        self,
        discord_id: int,
        username: str,
        display_name: str,
        recipe_code: str,
    ) -> bool:
        profile = self.player_repository.get_or_create_by_discord_id(
            discord_id=discord_id,
            username=username,
            display_name=display_name,
        )

        recipe = self.craft_repository.get_by_code(recipe_code)
        if recipe is None:
            return False

        inventory_items = self.inventory_repository.list_by_player_id(profile.player.id)

        if not self.craft_service.can_craft(recipe, inventory_items):
            return False

        for ingredient in recipe.ingredients:
            item = self.item_repository.get_by_code(ingredient.item_code)
            if item is None:
                return False

            removed = self.inventory_repository.remove_item(
                player_id=profile.player.id,
                item_definition_id=item.id,
                quantity=ingredient.quantity,
            )
            if not removed:
                return False

        result_item = self.item_repository.get_by_code(recipe.result_item_code)
        if result_item is None:
            return False

        self.inventory_repository.add_item(
            player_id=profile.player.id,
            item_definition_id=result_item.id,
            quantity=recipe.result_quantity,
        )

        return True