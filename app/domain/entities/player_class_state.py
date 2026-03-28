from dataclasses import dataclass
from datetime import datetime


@dataclass
class PlayerClassState:
    player_id: int
    current_class_id: int | None
    unlocked_at: datetime | None
    created_at: datetime
    updated_at: datetime