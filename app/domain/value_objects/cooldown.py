from dataclasses import dataclass
from datetime import datetime


@dataclass
class Cooldown:
    player_id: int
    action_key: str
    last_used_at: datetime | None
    next_available_at: datetime | None