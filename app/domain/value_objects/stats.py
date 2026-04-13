from dataclasses import dataclass


@dataclass
class Stats:
    max_hp: int
    attack: int
    defense: int
    crit_chance: float
    crit_damage: float
    dodge: float
    hp_regeneration: int