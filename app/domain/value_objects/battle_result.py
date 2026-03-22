from dataclasses import dataclass


@dataclass
class BattleResult:
    victory: bool
    turns: int
    player_remaining_hp: int
    mob_remaining_hp: int
    xp_gained: int
    gold_gained: int
    summary: str