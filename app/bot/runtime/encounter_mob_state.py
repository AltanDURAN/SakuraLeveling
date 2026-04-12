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