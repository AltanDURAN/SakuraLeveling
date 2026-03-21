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