from dataclasses import dataclass


@dataclass
class BattleTurnLog:
    turn_number: int
    player_damage_dealt: int
    player_crit: bool
    mob_damage_dealt: int
    player_dodged: bool
    player_hp_after: int
    mob_hp_after: int