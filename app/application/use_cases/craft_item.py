from dataclasses import dataclass, field

from app.domain.services.craft_service import (
    CraftRequirementsCheck,
    CraftService,
    IngredientStatus,
)
from app.infrastructure.db.repositories.craft_repository import CraftRepository
from app.infrastructure.db.repositories.inventory_repository import InventoryRepository
from app.infrastructure.db.repositories.item_repository import ItemRepository
from app.infrastructure.db.repositories.player_repository import PlayerRepository


@dataclass
class CraftFailure:
    """Détail enrichi d'un échec de craft (utile pour afficher le manque
    de ressources au joueur). Quand `success=False`, le caller peut lire
    `missing_ingredients` pour produire un récap.
    """

    success: bool
    message: str
    missing_ingredients: list[IngredientStatus] = field(default_factory=list)
    recipe_name: str = ""


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

    def execute_detailed(
        self,
        discord_id: int,
        username: str,
        display_name: str,
        recipe_code: str,
    ) -> CraftFailure:
        """Variante détaillée qui retourne un CraftFailure pour pouvoir
        afficher le manque de ressources. Le booléen historique reste
        exposé via `execute()` pour rétrocompatibilité avec les tests."""
        profile = self.player_repository.get_or_create_by_discord_id(
            discord_id=discord_id,
            username=username,
            display_name=display_name,
        )

        recipe = self.craft_repository.get_by_code(recipe_code)
        if recipe is None:
            return CraftFailure(
                success=False, message=f"❌ Recette `{recipe_code}` introuvable.",
            )

        inventory_items = self.inventory_repository.list_by_player_id(profile.player.id)

        check = self.craft_service.check_requirements(recipe, inventory_items)
        if not check.can_craft:
            return CraftFailure(
                success=False,
                message=f"❌ Ressources insuffisantes pour **{recipe.name}**.",
                missing_ingredients=[s for s in check.ingredients if not s.fulfilled],
                recipe_name=recipe.name,
            )

        for ingredient in recipe.ingredients:
            item = self.item_repository.get_by_code(ingredient.item_code)
            if item is None:
                return CraftFailure(
                    success=False,
                    message=f"❌ Item `{ingredient.item_code}` introuvable.",
                )

            removed = self.inventory_repository.remove_item(
                player_id=profile.player.id,
                item_definition_id=item.id,
                quantity=ingredient.quantity,
            )
            if not removed:
                return CraftFailure(
                    success=False,
                    message=f"❌ Échec de retrait de `{ingredient.item_code}`.",
                )

        result_item = self.item_repository.get_by_code(recipe.result_item_code)
        if result_item is None:
            return CraftFailure(
                success=False,
                message=f"❌ Item résultat `{recipe.result_item_code}` introuvable.",
            )

        self.inventory_repository.add_item(
            player_id=profile.player.id,
            item_definition_id=result_item.id,
            quantity=recipe.result_quantity,
        )

        # Quêtes hebdo + quotidiennes : on_craft (best effort)
        try:
            from app.application.use_cases.weekly_quests import (
                WeeklyQuestProgressService,
            )
            from app.application.use_cases.daily_quests import (
                DailyQuestProgressService,
            )
            from app.infrastructure.db.repositories.weekly_quest_repository import (
                WeeklyQuestRepository,
            )
            from app.infrastructure.db.repositories.daily_quest_repository import (
                DailyQuestRepository,
            )
            session = self.inventory_repository.session
            WeeklyQuestProgressService(WeeklyQuestRepository(session)).on_craft(
                profile.player.id, count=recipe.result_quantity,
            )
            DailyQuestProgressService(DailyQuestRepository(session)).on_craft(
                profile.player.id, count=recipe.result_quantity,
            )
        except Exception:
            pass

        return CraftFailure(
            success=True,
            message=f"✅ **{recipe.name}** craftée avec succès.",
            recipe_name=recipe.name,
        )

    def execute(
        self,
        discord_id: int,
        username: str,
        display_name: str,
        recipe_code: str,
    ) -> bool:
        """Wrapper rétrocompat (les tests existants assertent un bool)."""
        return self.execute_detailed(
            discord_id=discord_id, username=username,
            display_name=display_name, recipe_code=recipe_code,
        ).success