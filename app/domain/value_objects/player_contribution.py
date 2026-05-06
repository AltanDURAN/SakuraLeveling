from dataclasses import dataclass


@dataclass
class PlayerContribution:
    player_id: int
    user_id: int
    name: str
    damage_dealt: int = 0
    damage_tanked: int = 0
    hp_healed: int = 0
    dodges: int = 0
    survived: bool = True
    final_hp: int = 0
    max_hp: int = 0
