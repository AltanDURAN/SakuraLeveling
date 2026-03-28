from app.domain.entities.craft_ingredient import CraftIngredient
from app.domain.entities.craft_recipe import CraftRecipe
from app.domain.entities.item_definition import ItemDefinition
from app.domain.entities.player_inventory_item import PlayerInventoryItem
from app.domain.services.craft_service import CraftService


def build_inventory_item(code: str, quantity: int) -> PlayerInventoryItem:
    item_definition = ItemDefinition(
        id=1,
        code=code,
        name=code,
        description="",
        category="resource",
        rarity="common",
        stackable=True,
        max_stack=None,
        sell_price=0,
        buy_price=None,
        icon=None,
        stat_bonuses=None,
        created_at=None,
        updated_at=None,
    )

    return PlayerInventoryItem(
        id=1,
        player_id=1,
        item_definition=item_definition,
        quantity=quantity,
        created_at=None,
        updated_at=None,
    )


def build_recipe() -> CraftRecipe:
    return CraftRecipe(
        id=1,
        code="test_recipe",
        name="Test Recipe",
        result_item_code="result_item",
        result_quantity=1,
        ingredients=[
            CraftIngredient(item_code="item_a", quantity=2),
            CraftIngredient(item_code="item_b", quantity=1),
        ],
        created_at=None,
        updated_at=None,
    )


def test_can_craft_when_player_has_all_ingredients():
    service = CraftService()

    recipe = build_recipe()

    inventory = [
        build_inventory_item("item_a", 2),
        build_inventory_item("item_b", 1),
    ]

    assert service.can_craft(recipe, inventory) is True


def test_cannot_craft_if_missing_ingredient():
    service = CraftService()

    recipe = build_recipe()

    inventory = [
        build_inventory_item("item_a", 2),
        # item_b manquant
    ]

    assert service.can_craft(recipe, inventory) is False


def test_cannot_craft_if_not_enough_quantity():
    service = CraftService()

    recipe = build_recipe()

    inventory = [
        build_inventory_item("item_a", 1),  # insuffisant
        build_inventory_item("item_b", 1),
    ]

    assert service.can_craft(recipe, inventory) is False


def test_can_craft_with_extra_items_in_inventory():
    service = CraftService()

    recipe = build_recipe()

    inventory = [
        build_inventory_item("item_a", 5),
        build_inventory_item("item_b", 2),
        build_inventory_item("item_c", 99),  # inutile mais présent
    ]

    assert service.can_craft(recipe, inventory) is True