"""Elna, l'alchimiste (`/alchimiste`) : prépare des potions.

Le joueur fournit les ingrédients — des matériaux de FAMILLE (cf.
`alchemy_service`) — et paie la confection en or, indexée sur son niveau.
Préparation immédiate, par lot. La maîtrise d'Elna monte d'un cran par potion
préparée : remise sur la confection, puis une chance de potion offerte.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from app.domain.entities.artisan import AlchemistDefinition, MasteryTier
from app.domain.services import alchemy_service as alchemy
from app.domain.services.artisan_service import ArtisanService
from app.infrastructure.artisans import artisan_loader
from app.infrastructure.db.repositories.inventory_repository import InventoryRepository
from app.infrastructure.db.repositories.item_repository import ItemRepository
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.repositories.work_order_repository import WorkOrderRepository

#: Lot maximal en une fois (garde-fou de l'interface).
MAX_BATCH = 50


@dataclass(frozen=True)
class Ingredient:
    code: str
    name: str
    needed: int     # par potion
    owned: int


@dataclass(frozen=True)
class RecipeStatus:
    item_code: str
    item_name: str
    effect: str
    ingredients: tuple[Ingredient, ...]
    unit_fee: int           # or pour UNE potion, remise comprise
    max_count: int          # potions préparables tout de suite
    owned: int              # potions déjà dans l'inventaire


@dataclass(frozen=True)
class AlchemyStatus:
    level: int
    gold: int
    orders_completed: int
    tier: MasteryTier
    recipes: tuple[RecipeStatus, ...]

    def recipe(self, item_code: str) -> RecipeStatus | None:
        return next((r for r in self.recipes if r.item_code == item_code), None)


@dataclass(frozen=True)
class BrewResult:
    success: bool
    message: str
    item_name: str = ""
    quantity: int = 0
    bonus: int = 0
    gold: int = 0


class BrewPotionUseCase:
    def __init__(self, session, definition: AlchemistDefinition | None = None,
                 rng: random.Random | None = None) -> None:
        self.session = session
        self.definition = definition or artisan_loader.get_alchemist()
        self.rng = rng or random.Random()
        self.players = PlayerRepository(session)
        self.items = ItemRepository(session)
        self.inventory = InventoryRepository(session)
        self.orders = WorkOrderRepository(session)
        self.artisans = ArtisanService()

    # ------------------------------------------------------------ lecture --
    def status(self, player_id: int) -> AlchemyStatus:
        profile = self.players.get_profile_by_player_id(player_id)
        level = profile.progression.level if profile else 1
        gold = profile.resources.gold if profile else 0
        orders = self.orders.orders_completed(player_id, self.definition.code)
        tier = self.artisans.tier_for(self.definition, orders)
        owned: dict[str, int] = {}
        for entry in self.inventory.list_by_player_id(player_id):
            owned[entry.item_definition.code] = owned.get(entry.item_definition.code, 0) + entry.quantity

        recipes = []
        for recipe in self.definition.recipes:
            item = self.items.get_by_code(recipe.item_code)
            if item is None:
                continue
            ingredients = tuple(
                Ingredient(code, getattr(self.items.get_by_code(code), "name", code), qty, owned.get(code, 0))
                for code, qty in recipe.ingredients
            )
            recipes.append(RecipeStatus(
                item_code=recipe.item_code, item_name=item.name,
                effect=alchemy.effect_text(item.stat_bonuses),
                ingredients=ingredients,
                unit_fee=alchemy.brew_fee(recipe, level, 1, tier.gold_discount_pct),
                max_count=min(MAX_BATCH, alchemy.max_brewable(recipe, owned, gold, level, tier.gold_discount_pct)),
                owned=owned.get(recipe.item_code, 0),
            ))
        return AlchemyStatus(level, gold, orders, tier, tuple(recipes))

    # ---------------------------------------------------------- écriture --
    def brew(self, player_id: int, item_code: str, quantity: int) -> BrewResult:
        # Tout est revérifié ici : l'écran a pu être affiché il y a des minutes.
        quantity = max(1, min(MAX_BATCH, int(quantity)))
        status = self.status(player_id)
        recipe = self.definition.recipe(item_code)
        line = status.recipe(item_code)
        if recipe is None or line is None:
            return BrewResult(False, f"❌ {self.definition.name} ne connaît pas cette recette.")
        missing = [f"{i.needed * quantity - i.owned} × {i.name}" for i in line.ingredients
                   if i.owned < i.needed * quantity]
        if missing:
            return BrewResult(False, "❌ Il te manque " + ", ".join(missing) + ".", line.item_name)
        fee = alchemy.brew_fee(recipe, status.level, quantity, status.tier.gold_discount_pct)
        if status.gold < fee:
            return BrewResult(False, f"❌ Il te manque {fee - status.gold} or pour la confection.",
                              line.item_name)

        # Atomique : rien n'est validé avant la fin ; un ingrédient manquant
        # (course avec un échange) annule tout.
        for code, qty in recipe.ingredients:
            material = self.items.get_by_code(code)
            if material is None or not self.inventory.remove_item(
                    player_id, material.id, qty * quantity, commit=False):
                self.session.rollback()
                return BrewResult(False, "❌ Il te manque des ingrédients.", line.item_name)
        bonus = alchemy.bonus_potions(quantity, status.tier.bonus_pct, self.rng)
        potion = self.items.get_by_code(item_code)
        self.inventory.add_item(player_id, potion.id, quantity + bonus, commit=False)
        if fee:
            self.players.add_gold(player_id, -fee, commit=False)
        self.orders.increment_mastery(player_id, self.definition.code, gold_spent=fee, amount=quantity)
        self.session.commit()

        message = f"🧪 {quantity} × **{line.item_name}** préparée(s) pour {fee} or."
        if bonus:
            message += f" Elna t'en glisse {bonus} de plus 🎁."
        return BrewResult(True, message, line.item_name, quantity, bonus, fee)
