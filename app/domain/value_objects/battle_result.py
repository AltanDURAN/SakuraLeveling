from dataclasses import dataclass

from app.domain.value_objects.battle_turn_log import BattleTurnLog


@dataclass
class BattleResult:
    victory: bool
    turns: int
    player_remaining_hp: int
    mob_remaining_hp: int
    xp_gained: int
    gold_gained: int
    items_gained: list[tuple[str, int]]
    leveled_up: bool
    new_level: int | None
    summary: str
    turn_logs: list[BattleTurnLog]
    mob_name: str
    mob_image_name: str
    # Brut entrant total avant réduction par la défense — sert au tracking
    # "damage tanked" honnête (la défense a absorbé `raw - hp_lost`).
    player_total_raw_damage_taken: int = 0