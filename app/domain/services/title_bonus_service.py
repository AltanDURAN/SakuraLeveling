"""Application des effets passifs des titres débloqués.

Tous les titres débloqués par un joueur sont actifs en effet passif (pas
besoin de les "équiper" — l'équipement n'a qu'un rôle cosmétique d'affichage).
Ce service agrège leurs bonus dans une structure unifiée :
    - damage_bonus_vs_family : pct dégâts INFLIGÉS par famille
    - damage_reduction_from_family : pct dégâts REÇUS par famille
    - champion_all_stats_pct : pct global (titre Champion 1v1)
    - gold_xp_bonus_pct : pct gold/xp en combat (titre Farmer Fou)

Plusieurs titres ciblant la même famille s'additionnent (ex : titre A +10%
et titre B +5% → +15%). Bornage à 95% pour éviter les abus.
"""

from dataclasses import dataclass, field
from math import ceil

from app.domain.entities.title_definition import TitleDefinition
from app.domain.value_objects.stats import Stats


MAX_BONUS_PCT = 95


@dataclass
class TitleBonuses:
    """Bonus passifs cumulés à partir des titres débloqués."""

    damage_bonus_vs_family: dict[str, int] = field(default_factory=dict)
    damage_reduction_from_family: dict[str, int] = field(default_factory=dict)
    # Bonus "global" du titre Champion 1v1 (et autres futurs titres
    # exclusifs au même format) — pct multiplicatif/additif selon la stat.
    champion_all_stats_pct: int = 0
    # Bonus gold/xp en combat (titre Farmer Fou). S'applique uniquement au
    # détenteur, pas aux coéquipiers.
    gold_xp_bonus_pct: int = 0

    def damage_multiplier_vs(self, family: str) -> float:
        pct = min(MAX_BONUS_PCT, self.damage_bonus_vs_family.get(family, 0))
        return 1.0 + pct / 100

    def damage_received_multiplier_from(self, family: str) -> float:
        pct = min(MAX_BONUS_PCT, self.damage_reduction_from_family.get(family, 0))
        # Réduction → multiplicateur < 1
        return max(0.05, 1.0 - pct / 100)

    def apply_to_stats(self, stats: Stats) -> Stats:
        """Applique le bonus 'champion_all_stats' à un Stats VO.

        Convention demandée :
        - max_hp / attack / defense : +X% multiplicatif, arrondi entier supérieur
        - crit_chance / crit_damage / dodge : +X additif (pcts entiers)
        - speed / hp_regeneration : +X flat
        - 0% ⇒ Stats inchangé (no-op)
        """
        pct = self.champion_all_stats_pct
        if pct <= 0:
            return stats

        mult = 1 + pct / 100
        return Stats(
            max_hp=ceil(stats.max_hp * mult),
            attack=ceil(stats.attack * mult),
            defense=ceil(stats.defense * mult),
            crit_chance=stats.crit_chance + pct,
            crit_damage=stats.crit_damage + pct,
            dodge=stats.dodge + pct,
            hp_regeneration=stats.hp_regeneration + pct,
            speed=stats.speed + pct,
        )


class TitleBonusService:
    def aggregate(self, titles: list[TitleDefinition]) -> TitleBonuses:
        bonuses = TitleBonuses()
        for title in titles:
            for effect in title.effects:
                etype = effect.get("type")
                target = effect.get("target", "")
                value = int(effect.get("value", 0))

                if etype == "damage_bonus_vs_family" and target and value > 0:
                    bonuses.damage_bonus_vs_family[target] = (
                        bonuses.damage_bonus_vs_family.get(target, 0) + value
                    )
                elif etype == "damage_reduction_from_family" and target and value > 0:
                    bonuses.damage_reduction_from_family[target] = (
                        bonuses.damage_reduction_from_family.get(target, 0) + value
                    )
                elif etype == "champion_all_stats" and value > 0:
                    bonuses.champion_all_stats_pct += value
                elif etype == "gold_xp_bonus_pct" and value > 0:
                    bonuses.gold_xp_bonus_pct += value
                # Type inconnu : ignoré poliment (extensibilité)
        return bonuses
