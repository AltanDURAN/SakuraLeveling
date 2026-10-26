from __future__ import annotations

from dataclasses import dataclass

from app.domain.value_objects.stats import Stats


@dataclass(frozen=True)
class StatusEffectBonuses:
    """Agrégat des effets temporaires actifs d'un joueur.

    `all_stats_multiplier` : multiplicateur global (événements : petite
    fille), appliqué à TOUTES les stats de combat positives en fin de chaîne.
    `*_percent` : élixirs d'Elna (FRACTIONS, 0.10 = +10 %), ajoutés au POOL de
    pourcentages du socle par `StatsService` comme toute autre source — et
    seulement là où les élixirs comptent (combats de zone, world boss).
    """

    all_stats_multiplier: float = 1.0
    attack_percent: float = 0.0
    defense_percent: float = 0.0
    max_hp_percent: float = 0.0

    def apply_to_stats(self, stats: Stats) -> Stats:
        m = self.all_stats_multiplier
        if m == 1.0:
            return stats
        return Stats(
            max_hp=max(1, round(stats.max_hp * m)),
            attack=max(1, round(stats.attack * m)),
            defense=max(1, round(stats.defense * m)),
            speed=max(1, round(stats.speed * m)),
            crit_chance=max(0, round(stats.crit_chance * m)),
            crit_damage=max(100, round(stats.crit_damage * m)),
            dodge=max(0, round(stats.dodge * m)),
            hp_regeneration=max(0, round(stats.hp_regeneration * m)),
            mana_max=max(0, round(stats.mana_max * m)),
            mana_regeneration=max(0, round(stats.mana_regeneration * m)),
        )
