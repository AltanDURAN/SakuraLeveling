from dataclasses import dataclass
from datetime import datetime


@dataclass
class MobDefinition:
    id: int
    code: str
    name: str
    description: str
    max_hp: int
    attack: int
    defense: int
    xp_reward: int
    gold_reward: int
    created_at: datetime
    updated_at: datetime