from dataclasses import dataclass


@dataclass
class EncounterMobState:
    code: str
    name: str
    image_name: str
    current_hp: int
    max_hp: int
    attack: int
    defense: int
    speed: int
    crit_chance: int
    crit_damage: int
    dodge: int
    hp_regeneration: int
    # Élément SPAWNÉ (roulé au spawn, pondéré) — pilote la teinte + le badge de
    # la scène et le type d'essences droppées. "" = neutre.
    element: str = ""