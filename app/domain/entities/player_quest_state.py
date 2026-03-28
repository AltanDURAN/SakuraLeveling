from dataclasses import dataclass
from datetime import datetime


@dataclass
class PlayerQuestState:
    player_id: int
    quest_definition_id: int
    progress_quantity: int
    is_completed: bool
    is_claimed: bool
    created_at: datetime
    updated_at: datetime