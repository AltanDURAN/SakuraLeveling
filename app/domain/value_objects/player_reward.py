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
    # Pièce d'équipement lâchée par le monstre : (nom, rareté). Au plus une.
    gear: list[tuple[str, str]] = field(default_factory=list)
    #: Nom affiché des objets de `items` (code → nom), pour le récap.
    item_names: dict[str, str] = field(default_factory=dict)
    #: Niveau avant et après le combat (0 = inconnu : combat perdu, sans XP).
    level_before: int = 0
    level_after: int = 0
    #: Points à placer après le combat (montrés au passage d'un niveau).
    stat_points: int = 0
    skill_points: int = 0
    #: Noms des titres débloqués par ce combat.
    titles: list[str] = field(default_factory=list)
    #: L'XP a profité du coup de pouce des débuts.
    newcomer_bonus: bool = False

    @property
    def levels_gained(self) -> int:
        return max(0, self.level_after - self.level_before) if self.level_before else 0
