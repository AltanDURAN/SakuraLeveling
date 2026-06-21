"""Suppression en cascade d'un item : retire l'item ET toutes ses références
en base (inventaires, équipement, sets, trades, marketplace, shop, crafts).

Le nettoyage des JSON de contenu (items.json, shop_items.json, crafts.json,
mobs.json loot, family_drops.json) est géré côté webapp (content_sync), car
c'est une préoccupation de l'outil d'admin, pas du domaine.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.infrastructure.db.models.craft_model import (
    CraftRecipeIngredientModel,
    CraftRecipeModel,
)
from app.infrastructure.db.models.equipment_model import PlayerEquipmentItemModel
from app.infrastructure.db.models.equipment_set_model import PlayerEquipmentSetItemModel
from app.infrastructure.db.models.inventory_model import PlayerInventoryItemModel
from app.infrastructure.db.models.item_model import ItemDefinitionModel
from app.infrastructure.db.models.marketplace_listing_model import MarketplaceListingModel
from app.infrastructure.db.models.shop_item_model import ShopItemModel
from app.infrastructure.db.models.trade_model import TradeItemModel


@dataclass
class DeleteItemResult:
    deleted: bool
    code: str
    removed_refs: dict = field(default_factory=dict)
    recipes_removed: int = 0


# Tables qui référencent un item via item_definition_id.
_REF_MODELS = (
    PlayerInventoryItemModel,
    PlayerEquipmentItemModel,
    PlayerEquipmentSetItemModel,
    TradeItemModel,
    MarketplaceListingModel,
    ShopItemModel,
    CraftRecipeIngredientModel,
)


class DeleteItemUseCase:
    def execute(self, session: Session, code: str) -> DeleteItemResult:
        item = session.execute(
            select(ItemDefinitionModel).where(ItemDefinitionModel.code == code)
        ).scalar_one_or_none()
        if item is None:
            return DeleteItemResult(deleted=False, code=code)

        iid = item.id
        removed: dict = {}
        for model in _REF_MODELS:
            res = session.execute(
                delete(model).where(model.item_definition_id == iid)
            )
            if res.rowcount:
                removed[model.__tablename__] = res.rowcount

        # Recettes dont CET item est le résultat : on retire la recette + ses
        # ingrédients (sinon recette orpheline produisant un item inexistant).
        recipes = session.execute(
            select(CraftRecipeModel).where(
                CraftRecipeModel.result_item_definition_id == iid
            )
        ).scalars().all()
        for recipe in recipes:
            session.execute(
                delete(CraftRecipeIngredientModel).where(
                    CraftRecipeIngredientModel.craft_recipe_id == recipe.id
                )
            )
            session.delete(recipe)

        session.delete(item)
        session.commit()
        return DeleteItemResult(
            deleted=True, code=code, removed_refs=removed,
            recipes_removed=len(recipes),
        )
