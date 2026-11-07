from dataclasses import dataclass
from datetime import datetime


@dataclass
class Player:
    id: int
    discord_id: int
    username: str
    display_name: str
    created_at: datetime
    updated_at: datetime
    last_seen_at: datetime
    earned_rank: str = "F"
    combat_tactic: str = "egoiste"
    panoplie_bonus: str = "attack"
