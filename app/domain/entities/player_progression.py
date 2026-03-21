from dataclasses import dataclass
from datetime import datetime


@dataclass
class PlayerProgression:
    player_id: int
    level: int
    xp: int
    skill_points: int
    created_at: datetime
    updated_at: datetime