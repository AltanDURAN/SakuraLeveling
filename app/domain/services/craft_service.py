from app.domain.entities.craft_recipe import CraftRecipe
from app.domain.entities.player_inventory_item import PlayerInventoryItem


class CraftService:
    def can_craft(
        self,
        recipe: CraftRecipe,
        inventory_items: list[PlayerInventoryItem],
    ) -> bool:
        inventory_map = {
            item.item_definition.code: item.quantity
            for item in inventory_items
        }

        for ingredient in recipe.ingredients:
            if inventory_map.get(ingredient.item_code, 0) < ingredient.quantity:
                return False

        return True