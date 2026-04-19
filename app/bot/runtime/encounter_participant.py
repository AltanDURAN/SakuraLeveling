from dataclasses import dataclass

from app.domain.value_objects.stats import Stats


@dataclass
class EncounterParticipant:
    user_id: int
    player_id: int
    display_name: str
    avatar_url: str
    current_hp: int
    max_hp: int
    stats: Stats