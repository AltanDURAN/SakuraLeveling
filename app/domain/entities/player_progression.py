from dataclasses import dataclass
from datetime import datetime


@dataclass
class PlayerProgression:
    """Progression d'un joueur : niveau, XP et les DEUX monnaies de montée.

    `skill_points` alimente l'arbre de compétences (passifs, actifs, classes,
    stats secondaires en brut). `stat_points` alimente les trois stats de BASE
    — c'est le joueur qui choisit où les placer, comme dans un isekai.

    `points_attack` / `points_defense` / `points_max_hp` mémorisent la
    répartition déjà faite : on garde les POINTS plutôt que les stats
    calculées, pour pouvoir changer la valeur d'un point sans réécrire la base.
    """

    player_id: int
    level: int
    xp: int
    skill_points: int
    created_at: datetime
    updated_at: datetime
    stat_points: int = 0
    points_attack: int = 0
    points_defense: int = 0
    points_max_hp: int = 0

    @property
    def spent_stat_points(self) -> int:
        return self.points_attack + self.points_defense + self.points_max_hp
