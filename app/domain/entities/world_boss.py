"""Entité d'un world boss en cours.

Un seul boss actif à la fois (statut "active"). Quand le boss meurt, son
statut passe à "defeated" et un nouveau boss peut être spawné. Les HP du
boss sont conservés entre les combats — chaque participant l'use à
l'usure.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class WorldBossStatus(str, Enum):
    ACTIVE = "active"
    DEFEATED = "defeated"


@dataclass
class WorldBoss:
    id: int
    code: str
    name: str
    image_name: str
    max_hp: int
    current_hp: int
    attack: int
    defense: int
    speed: int
    crit_chance: int
    crit_damage: int
    dodge: int
    hp_regeneration: int
    status: WorldBossStatus
    spawned_at: datetime
    defeated_at: datetime | None
    channel_message_id: int | None
    element: str = ""

    @property
    def is_alive(self) -> bool:
        return self.status == WorldBossStatus.ACTIVE and self.current_hp > 0


@dataclass
class WorldBossParticipation:
    id: int
    boss_id: int
    player_id: int
    joined: bool
    damage_dealt: int
    damage_tanked: int
    hp_healed: int
    fights_count: int
    created_at: datetime
    updated_at: datetime
    voted_to_start: bool = False
