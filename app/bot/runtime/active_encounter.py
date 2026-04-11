from dataclasses import dataclass, field
from datetime import datetime, UTC, timedelta

from app.bot.runtime.encounter_participant import EncounterParticipant


@dataclass
class ActiveEncounter:
    mob_code: str
    mob_name: str
    spawn_image_url: str | None
    turn_image_urls: list[str]
    victory_image_url: str | None
    defeat_image_url: str | None
    flee_image_url: str | None
    message_id: int | None
    started_at: datetime
    ends_at: datetime
    participants: dict[int, EncounterParticipant] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        mob_code: str,
        mob_name: str,
        spawn_image_url: str | None,
        turn_image_urls: list[str],
        victory_image_url: str | None,
        defeat_image_url: str | None,
        flee_image_url: str | None,
        duration_minutes: int = 5,
    ) -> "ActiveEncounter":
        now = datetime.now(UTC)
        return cls(
            mob_code=mob_code,
            mob_name=mob_name,
            spawn_image_url=spawn_image_url,
            turn_image_urls=turn_image_urls,
            victory_image_url=victory_image_url,
            defeat_image_url=defeat_image_url,
            flee_image_url=flee_image_url,
            message_id=None,
            started_at=now,
            ends_at=now + timedelta(minutes=duration_minutes),
            participants={},
        )