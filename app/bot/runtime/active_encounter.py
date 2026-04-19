from dataclasses import dataclass, field
from datetime import datetime, UTC, timedelta

from app.bot.runtime.encounter_mob_state import EncounterMobState
from app.bot.runtime.encounter_participant import EncounterParticipant


@dataclass
class ActiveEncounter:
    mob_state: EncounterMobState
    victory_image_name: str
    defeat_image_name: str
    flee_image_name: str
    message_id: int | None
    started_at: datetime
    ends_at: datetime
    participants: dict[int, EncounterParticipant] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        mob_state: EncounterMobState,
        victory_image_name: str,
        defeat_image_name: str,
        flee_image_name: str,
        duration_minutes: int = 5,
    ) -> "ActiveEncounter":
        now = datetime.now(UTC)
        return cls(
            mob_state=mob_state,
            victory_image_name=victory_image_name,
            defeat_image_name=defeat_image_name,
            flee_image_name=flee_image_name,
            message_id=None,
            started_at=now,
            ends_at=now + timedelta(minutes=duration_minutes),
            participants={},
        )