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
    crit_chance: int
    crit_damage: int
    dodge: int
    hp_regeneration: int
    loot_table: list[dict] | None
    created_at: datetime
    updated_at: datetime