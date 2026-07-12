from dataclasses import dataclass


@dataclass
class Stats:
    """Stats de combat d'un joueur ou d'un monstre.

    Conventions des champs (toutes en entiers) :
    - max_hp, attack, defense, speed, hp_regeneration : valeurs absolues
    - mana_max, mana_regeneration : valeurs absolues (mana_regeneration = mana
      régénéré par minute HORS combat, comme hp_regeneration ; jamais en combat)
    - crit_chance, dodge : pourcentage 0..100 (50 = 50%)
    - crit_damage : pourcentage où 100 = neutre, 150 = ×1.5

    NB : le mana COURANT n'est pas une stat — il vit dans `PlayerManaState`
    (stockage dédié + `ManaRegenerationService`), exactement comme les PV
    courants vivent dans `PlayerHealthState`.
    """

    max_hp: int
    attack: int
    defense: int
    crit_chance: int
    crit_damage: int
    dodge: int
    hp_regeneration: int = 0
    speed: int = 5
    mana_max: int = 0
    mana_regeneration: int = 0