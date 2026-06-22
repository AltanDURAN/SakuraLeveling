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
    skill_slot_1: str | None = None
    skill_slot_2: str | None = None