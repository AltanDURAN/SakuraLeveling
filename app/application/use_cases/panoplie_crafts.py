"""Use cases pour `/craft_panoplie <nom>` et `/forge_panoplie <nom>`.

Deux phases :
1. `BuildPanoplieCraftPlanUseCase.execute(...)` calcule un plan :
   quelles pièces de la panoplie cible sont manquantes ET craftables sur
   la station demandée (forge ou craft), agrège les ingrédients
   nécessaires, et indique si le joueur a tout sous la main.
2. `ExecutePanoplieCraftsUseCase.execute(plan)` exécute toutes les
   recettes du plan séquentiellement (chaque craft consomme ses
   ingrédients et produit son item). Le caller appelle ce use case
   uniquement après confirmation du joueur (bouton du View).

Filtrage :
- `/forge_panoplie` ⇒ items dont la category est dans `FORGE_CATEGORIES`
- `/craft_panoplie` ⇒ items dont la category est PAS dans `FORGE_CATEGORIES`
- Item déjà possédé (en inventaire OU équipé) ⇒ skipé
- Item de la famille mais sans recette ⇒ skipé silencieusement
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.shared.enums import FORGE_CATEGORIES
from app.domain.entities.craft_recipe import CraftRecipe
from app.domain.entities.item_definition import ItemDefinition
from app.infrastructure.db.repositories.craft_repository import CraftRepository
from app.infrastructure.db.repositories.equipment_repository import EquipmentRepository
from app.infrastructure.db.repositories.inventory_repository import InventoryRepository
from app.infrastructure.db.repositories.item_repository import ItemRepository
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.sets.set_loader import (
    list_definitions as list_set_definitions,
)


@dataclass
class PanoplieCraftEntry:
    """Une recette à exécuter pour une pièce manquante."""

    recipe: CraftRecipe
    result_item: ItemDefinition


@dataclass
class PanoplieCraftPlan:
    """Plan complet d'un /craft_panoplie ou /forge_panoplie."""

    family: str
    family_name: str
    family_icon: str
    station: str  # "craft" ou "forge"
    entries: list[PanoplieCraftEntry] = field(default_factory=list)
    # Ingrédients agrégés : item_code → qty totale nécessaire
    total_ingredients: dict[str, int] = field(default_factory=dict)
    # Quantités possédées dans l'inventaire (item_code → qty)
    inventory_qty: dict[str, int] = field(default_factory=dict)
    # Manque : item_code → qty manquante (qty_needed - qty_owned, si > 0)
    missing_ingredients: dict[str, int] = field(default_factory=dict)
    # Lookup pour afficher le nom des items
    item_lookup: dict[str, ItemDefinition] = field(default_factory=dict)
    # Pièces de la famille déjà possédées (info)
    already_owned: list[ItemDefinition] = field(default_factory=list)

    @property
    def sufficient(self) -> bool:
        return not self.missing_ingredients

    @property
    def is_empty(self) -> bool:
        return len(self.entries) == 0


@dataclass
class PanoplieCraftResult:
    success: bool
    message: str
    crafted_items: list[str] = field(default_factory=list)


class BuildPanoplieCraftPlanUseCase:
    def __init__(
        self,
        player_repository: PlayerRepository,
        inventory_repository: InventoryRepository,
        equipment_repository: EquipmentRepository,
        item_repository: ItemRepository,
        craft_repository: CraftRepository,
    ) -> None:
        self.player_repository = player_repository
        self.inventory_repository = inventory_repository
        self.equipment_repository = equipment_repository
        self.item_repository = item_repository
        self.craft_repository = craft_repository

    def execute(
        self,
        discord_id: int,
        username: str,
        display_name: str,
        family: str,
        station: str,
    ) -> tuple[PanoplieCraftPlan | None, str | None]:
        """Renvoie (plan, error). Si error != None, plan est None."""
        family = (family or "").strip()
        station = station.strip().lower()
        if station not in ("craft", "forge"):
            return None, f"❌ Station inconnue : `{station}`."

        sets_def = list_set_definitions()
        set_def = sets_def.get(family)
        if set_def is None:
            return None, f"❌ Panoplie `{family}` introuvable."

        profile = self.player_repository.get_or_create_by_discord_id(
            discord_id=discord_id,
            username=username,
            display_name=display_name,
        )
        player_id = profile.player.id

        # Items possédés (inventaire ∪ équipés) — par def_id
        inventory = self.inventory_repository.list_by_player_id(player_id)
        equipped = self.equipment_repository.list_by_player_id(player_id)
        owned_def_ids = (
            {i.item_definition.id for i in inventory}
            | {e.item_definition.id for e in equipped}
        )

        # Quantités d'inventaire pour le calcul d'ingrédients
        inv_qty: dict[str, int] = {}
        for inv in inventory:
            inv_qty[inv.item_definition.code] = (
                inv_qty.get(inv.item_definition.code, 0) + inv.quantity
            )

        # Items de la famille avec un slot équipable
        all_items = self.item_repository.list_all()
        family_items = [
            it for it in all_items
            if (it.family or "").strip() == family and it.equipment_slot
        ]

        # Filtre par station
        in_forge = station == "forge"
        relevant = [
            it for it in family_items
            if (it.category in FORGE_CATEGORIES) == in_forge
        ]

        # Sépare déjà-possédés vs manquants
        already_owned = [it for it in relevant if it.id in owned_def_ids]
        missing_items = [it for it in relevant if it.id not in owned_def_ids]

        # Charge toutes les recettes une fois et indexe par result_item_code
        all_recipes = self.craft_repository.list_all()
        recipes_by_result = {r.result_item_code: r for r in all_recipes}

        plan = PanoplieCraftPlan(
            family=family,
            family_name=set_def.get("name", family),
            family_icon=set_def.get("icon", "✨"),
            station=station,
            already_owned=already_owned,
        )

        # Lookup items par code (utile pour afficher les ingrédients)
        plan.item_lookup = {it.code: it for it in all_items}
        plan.inventory_qty = inv_qty

        # Construit les entrées : 1 par item manquant qui a une recette
        for it in missing_items:
            recipe = recipes_by_result.get(it.code)
            if recipe is None:
                continue
            plan.entries.append(
                PanoplieCraftEntry(recipe=recipe, result_item=it)
            )
            for ing in recipe.ingredients:
                plan.total_ingredients[ing.item_code] = (
                    plan.total_ingredients.get(ing.item_code, 0)
                    + ing.quantity
                )

        # Calcul du manque
        for code, needed in plan.total_ingredients.items():
            owned = inv_qty.get(code, 0)
            if owned < needed:
                plan.missing_ingredients[code] = needed - owned

        return plan, None


class ExecutePanoplieCraftsUseCase:
    """Exécute en séquence toutes les recettes d'un plan validé.

    Pré-condition : le plan a `sufficient=True` au moment de la
    construction. On revérifie ici aussi (au cas où l'inventaire change
    entre la preview et la confirmation, ex : trade en parallèle).
    """

    def __init__(
        self,
        player_repository: PlayerRepository,
        inventory_repository: InventoryRepository,
        item_repository: ItemRepository,
    ) -> None:
        self.player_repository = player_repository
        self.inventory_repository = inventory_repository
        self.item_repository = item_repository

    def execute(
        self,
        discord_id: int,
        username: str,
        display_name: str,
        plan: PanoplieCraftPlan,
    ) -> PanoplieCraftResult:
        if plan.is_empty:
            return PanoplieCraftResult(
                success=False,
                message="❌ Aucune pièce à crafter.",
            )

        profile = self.player_repository.get_or_create_by_discord_id(
            discord_id=discord_id,
            username=username,
            display_name=display_name,
        )
        player_id = profile.player.id

        # Revérification : ressources toujours là ?
        current_inv = self.inventory_repository.list_by_player_id(player_id)
        current_qty: dict[str, int] = {}
        for inv in current_inv:
            current_qty[inv.item_definition.code] = (
                current_qty.get(inv.item_definition.code, 0) + inv.quantity
            )
        for code, needed in plan.total_ingredients.items():
            if current_qty.get(code, 0) < needed:
                return PanoplieCraftResult(
                    success=False,
                    message=(
                        f"❌ Plus assez de **{code}** pour finir "
                        f"(votre inventaire a changé). Re-tente la commande."
                    ),
                )

        # Exécute chaque craft : retire ingrédients, ajoute résultat
        crafted_names: list[str] = []
        for entry in plan.entries:
            recipe = entry.recipe
            for ing in recipe.ingredients:
                ing_item = self.item_repository.get_by_code(ing.item_code)
                if ing_item is None:
                    continue
                self.inventory_repository.remove_item(
                    player_id=player_id,
                    item_definition_id=ing_item.id,
                    quantity=ing.quantity,
                )
            result_item = self.item_repository.get_by_code(
                recipe.result_item_code,
            )
            if result_item is None:
                continue
            self.inventory_repository.add_item(
                player_id=player_id,
                item_definition_id=result_item.id,
                quantity=recipe.result_quantity,
            )
            crafted_names.append(entry.result_item.name)

        verb = "forgée(s)" if plan.station == "forge" else "craftée(s)"
        return PanoplieCraftResult(
            success=True,
            message=(
                f"✅ {len(crafted_names)} pièce(s) {verb} pour la "
                f"panoplie **{plan.family_icon} {plan.family_name}**."
            ),
            crafted_items=crafted_names,
        )
