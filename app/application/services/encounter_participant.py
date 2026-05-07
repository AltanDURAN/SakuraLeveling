"""Snapshot d'un participant à un encounter (état runtime).

Vit dans la couche application pour rester importable par le service
d'orchestration `EncounterService` sans introduire de dépendance vers la
couche bot.
"""

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
