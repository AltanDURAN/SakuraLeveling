from dataclasses import dataclass


@dataclass
class Stats:
    """Stats de combat d'un joueur ou d'un monstre.

    Conventions des champs (toutes en entiers) :
    - max_hp, attack, defense, speed, hp_regeneration : valeurs absolues
    - crit_chance, dodge : pourcentage 0..100 (50 = 50%)
    - crit_damage : pourcentage où 100 = neutre, 150 = ×1.5
    """

    max_hp: int
    attack: int
    defense: int
    crit_chance: int
    crit_damage: int
    dodge: int
    hp_regeneration: int = 0
    speed: int = 5