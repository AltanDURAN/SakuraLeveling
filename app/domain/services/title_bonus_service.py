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
    # Bonus flat additifs sur les stats (Bourreau pour crit_damage,
    # Intouchable pour dodge). Ils s'additionnent au champion_all_stats.
    crit_damage_flat: int = 0
    dodge_flat: int = 0
    # Bonus drop rate vs un mob_code particulier (Chasseur Légendaire).
    # Multiplicatif sur le drop_rate de base (préserve la rareté des items
    # rares). Plusieurs titres ciblant le même mob s'additionnent.
    drop_rate_bonus_vs_mob: dict[str, int] = field(default_factory=dict)
    # Items octroyés à chaque /daily (Taverne Addict). Liste de tuples
    # (item_code, quantity).
    daily_bonus_items: list[tuple[str, int]] = field(default_factory=list)

    def damage_multiplier_vs(self, family: str) -> float:
        pct = min(MAX_BONUS_PCT, self.damage_bonus_vs_family.get(family, 0))
        return 1.0 + pct / 100

    def damage_received_multiplier_from(self, family: str) -> float:
        pct = min(MAX_BONUS_PCT, self.damage_reduction_from_family.get(family, 0))
        # Réduction → multiplicateur < 1
        return max(0.05, 1.0 - pct / 100)

    def drop_rate_multiplier_for_mob(self, mob_code: str) -> float:
        """Renvoie le multiplicateur drop_rate spécifique à ce mob (1.0 si
        aucun titre Chasseur Légendaire ciblé n'est débloqué)."""
        pct = self.drop_rate_bonus_vs_mob.get(mob_code, 0)
        return 1.0 + pct / 100

    def apply_to_stats(self, stats: Stats) -> Stats:
        """Applique tous les bonus passifs des titres à un Stats VO.

        Convention demandée :
        - champion_all_stats_pct (Champion 1v1) :
            - max_hp / attack / defense : +X% multiplicatif, ceil sur les fractions
            - crit_chance / crit_damage / dodge : +X additif (pcts entiers)
            - speed / hp_regeneration : +X flat
        - crit_damage_flat (Bourreau) : +X additif sur crit_damage.
        - dodge_flat (Intouchable) : +X additif sur dodge.

        Si tous les bonus sont à 0 ⇒ Stats inchangé.
        """
        champion_pct = self.champion_all_stats_pct
        crit_dmg_extra = self.crit_damage_flat
        dodge_extra = self.dodge_flat

        if champion_pct <= 0 and crit_dmg_extra <= 0 and dodge_extra <= 0:
            return stats

        if champion_pct > 0:
            mult = 1 + champion_pct / 100
            max_hp = ceil(stats.max_hp * mult)
            attack = ceil(stats.attack * mult)
            defense = ceil(stats.defense * mult)
        else:
            mult = 1.0
            max_hp = stats.max_hp
            attack = stats.attack
            defense = stats.defense

        return Stats(
            max_hp=max_hp,
            attack=attack,
            defense=defense,
            crit_chance=stats.crit_chance + champion_pct,
            crit_damage=stats.crit_damage + champion_pct + crit_dmg_extra,
            dodge=stats.dodge + champion_pct + dodge_extra,
            hp_regeneration=stats.hp_regeneration + champion_pct,
            speed=stats.speed + champion_pct,
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
                elif etype == "crit_damage_flat" and value > 0:
                    bonuses.crit_damage_flat += value
                elif etype == "dodge_flat" and value > 0:
                    bonuses.dodge_flat += value
                elif etype == "drop_rate_bonus_vs_mob" and target and value > 0:
                    bonuses.drop_rate_bonus_vs_mob[target] = (
                        bonuses.drop_rate_bonus_vs_mob.get(target, 0) + value
                    )
                elif etype == "daily_bonus_item" and target and value > 0:
                    bonuses.daily_bonus_items.append((target, value))
                # Type inconnu : ignoré poliment (extensibilité)
        return bonuses
