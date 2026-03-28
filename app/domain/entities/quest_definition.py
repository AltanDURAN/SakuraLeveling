from dataclasses import dataclass
from datetime import datetime


@dataclass
class QuestDefinition:
    id: int
    code: str
    name: str
    description: str
    objective_type: str
    target_code: str
    required_quantity: int
    reward_gold: int
    reward_xp: int
    reward_items: list[dict] | None
    created_at: datetime
    updated_at: datetime