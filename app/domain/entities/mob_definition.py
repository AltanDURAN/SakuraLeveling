from dataclasses import dataclass
from datetime import datetime


@dataclass
class MobDefinition:
    id: int
    code: str
    name: str
    description: str
    image_name: str | None
    max_hp: int
    current_hp: int
    attack: int
    defense: int
    xp_reward: int
    gold_reward: int
    spawn_weight: int
    speed: int
    loot_table: list[dict] | None
    created_at: datetime
    updated_at: datetime