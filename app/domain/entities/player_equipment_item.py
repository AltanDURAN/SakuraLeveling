from dataclasses import dataclass
from datetime import datetime

from app.domain.entities.item_definition import ItemDefinition


@dataclass
class PlayerEquipmentItem:
    id: int
    player_id: int
    slot: str
    item_definition: ItemDefinition
    created_at: datetime
    updated_at: datetime
    # Exemplaire porté (équipement v2) : rareté et forge sacrée de CETTE copie.
    rarity: str = "common"
    forge_level: int = 0
    gear_id: int | None = None