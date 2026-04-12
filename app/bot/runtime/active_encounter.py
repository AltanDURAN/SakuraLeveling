from dataclasses import dataclass, field
from datetime import datetime, UTC, timedelta

from app.bot.runtime.encounter_participant import EncounterParticipant


@dataclass
class ActiveEncounter:
    mob_code: str
    mob_name: str
    spawn_image_name: str
    turn_image_names: list[str]
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
        mob_code: str,
        mob_name: str,
        spawn_image_name: str,
        turn_image_names: list[str],
        victory_image_name: str,
        defeat_image_name: str,
        flee_image_name: str,
        duration_minutes: int = 1,
    ) -> "ActiveEncounter":
        now = datetime.now(UTC)
        return cls(
            mob_code=mob_code,
            mob_name=mob_name,
            spawn_image_name=spawn_image_name,
            turn_image_names=turn_image_names,
            victory_image_name=victory_image_name,
            defeat_image_name=defeat_image_name,
            flee_image_name=flee_image_name,
            message_id=None,
            started_at=now,
            ends_at=now + timedelta(minutes=duration_minutes),
            participants={},
        )