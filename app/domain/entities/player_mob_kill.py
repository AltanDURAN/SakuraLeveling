from dataclasses import dataclass
from datetime import datetime


@dataclass
class PlayerMobKill:
    id: int
    player_id: int
    mob_code: str
    kill_count: int
    created_at: datetime
    updated_at: datetime
