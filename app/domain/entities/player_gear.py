from dataclasses import dataclass
from datetime import datetime

from app.domain.entities.item_definition import ItemDefinition


@dataclass
class PlayerGear:
    """Un exemplaire d'équipement possédé (cf. PlayerGearModel)."""
    id: int
    player_id: int
    item_definition: ItemDefinition
    rarity: str
    forge_level: int
    equipped_slot: str | None
    source: str
    created_at: datetime
    listed: bool = False

    @property
    def equipped(self) -> bool:
        return self.equipped_slot is not None
