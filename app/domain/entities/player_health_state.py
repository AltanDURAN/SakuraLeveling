from dataclasses import dataclass
from datetime import datetime


@dataclass
class PlayerHealthState:
    player_id: int
    current_hp: int
    updated_at: datetime