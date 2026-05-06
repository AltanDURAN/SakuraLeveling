from dataclasses import dataclass
from datetime import datetime


@dataclass
class PlayerCareerStats:
    player_id: int
    gold_earned_total: int = 0
    damage_dealt_total: int = 0
    damage_tanked_total: int = 0
    hp_healed_total: int = 0
    dodges_total: int = 0
    combats_fought: int = 0
    combats_won: int = 0
    combats_lost: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None
