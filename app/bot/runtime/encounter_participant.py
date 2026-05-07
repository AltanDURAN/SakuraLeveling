"""Re-export pour rétro-compatibilité — la définition vit désormais dans
la couche application (`app.application.services.encounter_participant`).

Évite la violation d'architecture : `EncounterService` (application) ne
peut pas importer de la couche bot.
"""

from app.application.services.encounter_participant import EncounterParticipant

__all__ = ["EncounterParticipant"]
