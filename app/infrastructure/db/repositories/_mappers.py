"""Mappers partagés entre repositories.

Mutualise les conversions Model -> Entity domaine recopiées d'un repo à l'autre.
Cf. audit Phase 1 finding F2 : le mapping ItemDefinitionModel -> ItemDefinition
(16 champs) était dupliqué dans 5 repos. Toute évolution = 5 endroits à toucher.
"""

from __future__ import annotations

from app.domain.entities.item_definition import ItemDefinition
from app.infrastructure.db.models.item_model import ItemDefinitionModel


def map_item_definition(model: ItemDefinitionModel) -> ItemDefinition:
    """Convertit un ItemDefinitionModel en ItemDefinition (entité domaine)."""
    return ItemDefinition(
        id=model.id,
        code=model.code,
        name=model.name,
        description=model.description,
        category=model.category,
        rarity=model.rarity,
        stackable=model.stackable,
        max_stack=model.max_stack,
        sell_price=model.sell_price,
        buy_price=model.buy_price,
        icon=model.icon,
        stat_bonuses=model.stat_bonuses_json,
        equipment_slot=model.equipment_slot,
        requires_two_hands=bool(model.requires_two_hands or False),
        family=getattr(model, "family", "") or "",
        created_at=model.created_at,
        updated_at=model.updated_at,
    )
