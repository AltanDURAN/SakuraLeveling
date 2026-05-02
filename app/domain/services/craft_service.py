from dataclasses import dataclass

from app.domain.entities.craft_recipe import CraftRecipe
from app.domain.entities.player_inventory_item import PlayerInventoryItem


@dataclass
class IngredientStatus:
    item_code: str
    item_name: str  # "?" si introuvable côté caller — sera enrichi en aval
    required: int
    owned: int

    @property
    def missing(self) -> int:
        return max(0, self.required - self.owned)

    @property
    def fulfilled(self) -> bool:
        return self.owned >= self.required


@dataclass
class CraftRequirementsCheck:
    can_craft: bool
    ingredients: list[IngredientStatus]


class CraftService:
    def can_craft(
        self,
        recipe: CraftRecipe,
        inventory_items: list[PlayerInventoryItem],
    ) -> bool:
        return self.check_requirements(recipe, inventory_items).can_craft

    def check_requirements(
        self,
        recipe: CraftRecipe,
        inventory_items: list[PlayerInventoryItem],
    ) -> CraftRequirementsCheck:
        """Renvoie le détail de chaque ingrédient (possédé vs requis).
        Permet d'afficher au joueur ce qui lui manque précisément."""
        # Map code → (quantity, name) pour récupérer aussi le nom si dispo
        inventory_map: dict[str, tuple[int, str]] = {
            item.item_definition.code: (item.quantity, item.item_definition.name)
            for item in inventory_items
        }

        statuses: list[IngredientStatus] = []
        for ingredient in recipe.ingredients:
            owned, name = inventory_map.get(ingredient.item_code, (0, ""))
            statuses.append(
                IngredientStatus(
                    item_code=ingredient.item_code,
                    item_name=name or ingredient.item_code,
                    required=ingredient.quantity,
                    owned=owned,
                )
            )

        can_craft_now = all(s.fulfilled for s in statuses)
        return CraftRequirementsCheck(can_craft=can_craft_now, ingredients=statuses)