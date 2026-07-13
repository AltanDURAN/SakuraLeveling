from dataclasses import dataclass, field

from app.domain.value_objects.player_contribution import PlayerContribution


@dataclass(frozen=True)
class EssenceGain:
    """Essences élémentaires gagnées sur un kill + niveaux d'affinité montés
    en conséquence (auto-conversion). Surfacé dans le récap de combat."""

    element: str
    essences_gained: int
    affinity_before: int
    affinity_after: int

    @property
    def leveled_up(self) -> bool:
        return self.affinity_after > self.affinity_before


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
    contribution_share: float = 0.0  # 0..1, part de contribution au combat
    essence_gains: list[EssenceGain] = field(default_factory=list)
