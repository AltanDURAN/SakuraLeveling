from dataclasses import dataclass

from app.domain.entities.player import Player
from app.domain.entities.player_progression import PlayerProgression
from app.domain.entities.player_resources import PlayerResources


@dataclass
class PlayerProfile:
    player: Player
    progression: PlayerProgression
    resources: PlayerResources