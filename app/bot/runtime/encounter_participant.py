from dataclasses import dataclass


@dataclass
class EncounterParticipant:
    user_id: int
    player_id: int
    display_name: str
    avatar_url: str
    current_hp: int
    max_hp: int