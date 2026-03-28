from dataclasses import dataclass
from datetime import datetime


@dataclass
class PlayerProfession:
    player_id: int
    profession_definition_id: int
    level: int
    xp: int
    created_at: datetime
    updated_at: datetime