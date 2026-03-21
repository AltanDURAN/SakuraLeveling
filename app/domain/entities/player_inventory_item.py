from dataclasses import dataclass
from datetime import datetime

from app.domain.entities.item_definition import ItemDefinition


@dataclass
class PlayerInventoryItem:
    id: int
    player_id: int
    item_definition: ItemDefinition
    quantity: int
    created_at: datetime
    updated_at: datetime