from dataclasses import dataclass
from datetime import datetime


@dataclass
class PlayerResources:
    player_id: int
    gold: int
    created_at: datetime
    updated_at: datetime