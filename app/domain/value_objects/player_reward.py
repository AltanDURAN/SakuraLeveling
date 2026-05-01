from dataclasses import dataclass, field

from app.domain.value_objects.player_contribution import PlayerContribution


@dataclass
class PlayerReward:
    player_id: int
    user_id: int
    name: str
    avatar_url: str
    gold: int
    xp: int
    items: list[tuple[str, int]] = field(default_factory=list)
    contribution: PlayerContribution | None = None
