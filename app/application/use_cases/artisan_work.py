"""Cas d'usage des artisans : commander un travail, le récupérer, l'annuler.

Règles du système :
  • le joueur paie les INGRÉDIENTS et l'OR au moment de la commande — la
    matière est engagée dès que l'artisan s'y met ;
  • un seul travail actif par artisan (garanti par un index unique partiel) ;
  • annuler rend les ingrédients et rembourse une part de l'or ;
  • chaque travail RÉCUPÉRÉ fait monter la maîtrise de l'artisan pour ce joueur.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.domain.entities.artisan import ArtisanDefinition
from app.domain.services.artisan_service import ArtisanService, WorkQuote
from app.domain.services.craft_service import CraftService, IngredientStatus
from app.domain.services.item_power_service import ItemPowerService
from app.infrastructure.db.repositories.craft_repository import CraftRepository
from app.infrastructure.db.repositories.inventory_repository import (
    InventoryRepository,
)
from app.infrastructure.db.repositories.item_repository import ItemRepository
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.repositories.work_order_repository import (
    WorkOrderRepository,
)


@dataclass
class WorkOrderResult:
    success: bool
    message: str
    order_id: int | None = None
    ready_in_seconds: int = 0
    instant: bool = False


@dataclass
class WorkPreview:
    """Tout ce qu'il faut pour afficher la fiche d'un travail avant de le lancer."""

    recipe_code: str
    item_code: str
    item_name: str
    item_category: str
    result_quantity: int
    stat_bonuses: dict
    quote: WorkQuote
    ingredients: list[IngredientStatus] = field(default_factory=list)
    player_gold: int = 0

    @property
    def has_ingredients(self) -> bool:
        return all(i.fulfilled for i in self.ingredients)

    @property
    def can_afford(self) -> bool:
        return self.player_gold >= self.quote.gold_cost

    @property
    def can_start(self) -> bool:
        return self.quote.accepted and self.has_ingredients and self.can_afford

    @property
    def blocking_reason(self) -> str:
        if not self.quote.accepted:
            needed = self.quote.required_tier
            if needed is None:
                return (
                    "Pièce trop puissante : même à son meilleur niveau, "
                    "il ne saurait pas la faire."
                )
            return (
                f"Pièce trop puissante pour son niveau actuel — "
                f"il lui faut être **{needed.name}**."
            )
        if not self.has_ingredients:
            missing = [i for i in self.ingredients if not i.fulfilled]
            details = ", ".join(
                f"{i.item_name} ×{i.missing}" for i in missing[:4]
            )
            return f"Ingrédients manquants : {details}."
        if not self.can_afford:
            return (
                f"Il te manque {self.quote.gold_cost - self.player_gold} or "
                f"pour payer son travail."
            )
        return ""


class ArtisanWorkUseCase:
    def __init__(
        self,
        player_repository: PlayerRepository,
        inventory_repository: InventoryRepository,
        item_repository: ItemRepository,
        craft_repository: CraftRepository,
        work_order_repository: WorkOrderRepository,
        artisan_service: ArtisanService,
        item_power_service: ItemPowerService | None = None,
        craft_service: CraftService | None = None,
    ) -> None:
        self.players = player_repository
        self.inventory = inventory_repository
        self.items = item_repository
        self.recipes = craft_repository
        self.orders = work_order_repository
        self.artisans = artisan_service
        self.power = item_power_service or ItemPowerService()
        self.crafts = craft_service or CraftService()

    # ------------------------------------------------------------ lecture --
    def recipes_for(self, definition: ArtisanDefinition) -> list:
        """Recettes que CE PNJ sait faire, d'après la catégorie du résultat."""
        out = []
        for recipe in self.recipes.list_all():
            item = self.items.get_by_code(recipe.result_item_code)
            if item is not None and definition.handles_category(item.category):
                out.append(recipe)
        return out

    def preview(
        self,
        definition: ArtisanDefinition,
        player_id: int,
        recipe_code: str,
    ) -> WorkPreview | None:
        recipe = self.recipes.get_by_code(recipe_code)
        if recipe is None:
            return None
        item = self.items.get_by_code(recipe.result_item_code)
        if item is None:
            return None

        inventory_items = self.inventory.list_by_player_id(player_id)
        check = self.crafts.check_requirements(recipe, inventory_items)
        # `check_requirements` ne connaît le nom d'un ingrédient que si le
        # joueur en possède déjà : sans ça, tout ce qui manque s'affiche en
        # code brut (« c_ur_corrompu ») — précisément ce qu'il faut aller
        # chercher, donc ce qu'il faut nommer correctement.
        for status in check.ingredients:
            if status.item_name == status.item_code:
                known = self.items.get_by_code(status.item_code)
                if known is not None:
                    status.item_name = known.name
        power = self.power.marginal_power(item.stat_bonuses)
        completed = self.orders.orders_completed(player_id, definition.code)
        profile = self.players.get_profile_by_player_id(player_id)

        return WorkPreview(
            recipe_code=recipe.code,
            item_code=item.code,
            item_name=item.name,
            item_category=item.category,
            result_quantity=recipe.result_quantity,
            stat_bonuses=item.stat_bonuses or {},
            quote=self.artisans.quote(definition, power, completed),
            ingredients=check.ingredients,
            player_gold=profile.resources.gold if profile else 0,
        )

    # ----------------------------------------------------------- commande --
    def start(
        self,
        definition: ArtisanDefinition,
        player_id: int,
        recipe_code: str,
        notify_channel_id: int = 0,
    ) -> WorkOrderResult:
        if self.orders.get_active(player_id, definition.code) is not None:
            return WorkOrderResult(
                success=False,
                message=(
                    f"⏳ {definition.name} a déjà un travail en cours pour toi. "
                    f"Récupère-le ou annule-le avant d'en lancer un autre."
                ),
            )

        preview = self.preview(definition, player_id, recipe_code)
        if preview is None:
            return WorkOrderResult(
                success=False, message="❌ Cette recette n'existe pas.",
            )
        if not preview.can_start:
            return WorkOrderResult(
                success=False, message=f"❌ {preview.blocking_reason}",
            )

        item = self.items.get_by_code(preview.item_code)
        profile = self.players.get_profile_by_player_id(player_id)
        if item is None or profile is None:
            return WorkOrderResult(success=False, message="❌ Joueur introuvable.")

        # Débit : ingrédients puis or. On revérifie l'or ici — le devis a pu
        # être affiché il y a plusieurs minutes.
        if profile.resources.gold < preview.quote.gold_cost:
            return WorkOrderResult(
                success=False,
                message="❌ Tu n'as plus assez d'or pour payer ce travail.",
            )

        recipe = self.recipes.get_by_code(recipe_code)
        for ingredient in recipe.ingredients:
            ing_item = self.items.get_by_code(ingredient.item_code)
            if ing_item is None:
                return WorkOrderResult(
                    success=False,
                    message=f"❌ Ingrédient inconnu : `{ingredient.item_code}`.",
                )
            removed = self.inventory.remove_item(
                player_id, ing_item.id, ingredient.quantity,
            )
            if not removed:
                return WorkOrderResult(
                    success=False,
                    message=f"❌ Ingrédient manquant : {ing_item.name}.",
                )

        self.players.add_gold(player_id, -preview.quote.gold_cost)

        order = self.orders.create(
            player_id=player_id,
            artisan_code=definition.code,
            recipe_code=recipe.code,
            result_item_definition_id=item.id,
            result_quantity=recipe.result_quantity,
            gold_paid=preview.quote.gold_cost,
            item_power=preview.quote.item_power,
            duration_seconds=preview.quote.duration_seconds,
            notify_channel_id=notify_channel_id,
        )
        return WorkOrderResult(
            success=True,
            message="",
            order_id=order.id,
            ready_in_seconds=preview.quote.duration_seconds,
            instant=preview.quote.duration_seconds <= 0,
        )

    # --------------------------------------------------------- récupérer --
    def collect(
        self, definition: ArtisanDefinition, player_id: int,
    ) -> WorkOrderResult:
        order = self.orders.get_active(player_id, definition.code)
        if order is None:
            return WorkOrderResult(
                success=False,
                message=f"❌ {definition.name} n'a aucun travail en cours pour toi.",
            )
        from app.infrastructure.db.models.work_order_model import STATUS_READY

        if order.status != STATUS_READY:
            return WorkOrderResult(
                success=False,
                message=f"⏳ Ce n'est pas encore prêt. Laisse-lui le temps.",
            )

        self.inventory.add_item(
            player_id, order.result_item_definition_id, order.result_quantity,
        )
        self.orders.mark_collected(order.id)
        self.orders.increment_mastery(
            player_id, definition.code, gold_spent=order.gold_paid,
        )
        return WorkOrderResult(success=True, message="", order_id=order.id)

    # ----------------------------------------------------------- annuler --
    def cancel(
        self, definition: ArtisanDefinition, player_id: int,
    ) -> WorkOrderResult:
        order = self.orders.get_active(player_id, definition.code)
        if order is None:
            return WorkOrderResult(
                success=False,
                message=f"❌ Aucun travail à annuler chez {definition.name}.",
            )

        recipe = self.recipes.get_by_code(order.recipe_code)
        restored: list[str] = []
        if recipe is not None:
            for ingredient in recipe.ingredients:
                ing_item = self.items.get_by_code(ingredient.item_code)
                if ing_item is not None:
                    self.inventory.add_item(
                        order.player_id, ing_item.id, ingredient.quantity,
                    )
                    restored.append(f"{ing_item.name} ×{ingredient.quantity}")

        refund = self.artisans.refund_for(order.gold_paid)
        if refund:
            self.players.add_gold(order.player_id, refund)
        self.orders.mark_cancelled(order.id)

        detail = f" Ingrédients rendus : {', '.join(restored)}." if restored else ""
        return WorkOrderResult(
            success=True,
            message=(
                f"🚫 Travail annulé. {definition.name} garde "
                f"{order.gold_paid - refund} or pour la peine "
                f"(**{refund} or** rendus).{detail}"
            ),
        )
