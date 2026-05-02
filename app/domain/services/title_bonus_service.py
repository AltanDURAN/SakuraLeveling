"""Application des effets passifs des titres débloqués.

Tous les titres débloqués par un joueur sont actifs en effet passif (pas
besoin de les "équiper" — l'équipement n'a qu'un rôle cosmétique d'affichage).
Ce service agrège leurs bonus en deux dictionnaires {family: pct} :
    - damage_bonus_vs_family : multiplicateur additif des dégâts INFLIGÉS
    - damage_reduction_from_family : multiplicateur additif des dégâts REÇUS

Plusieurs titres ciblant la même famille s'additionnent (ex : titre A +10%
et titre B +5% → +15%). Bornage à 95% pour éviter les abus.
"""

from dataclasses import dataclass, field

from app.domain.entities.title_definition import TitleDefinition


MAX_BONUS_PCT = 95


@dataclass
class TitleBonuses:
    """Bonus passifs cumulés à partir des titres débloqués."""

    damage_bonus_vs_family: dict[str, int] = field(default_factory=dict)
    damage_reduction_from_family: dict[str, int] = field(default_factory=dict)

    def damage_multiplier_vs(self, family: str) -> float:
        pct = min(MAX_BONUS_PCT, self.damage_bonus_vs_family.get(family, 0))
        return 1.0 + pct / 100

    def damage_received_multiplier_from(self, family: str) -> float:
        pct = min(MAX_BONUS_PCT, self.damage_reduction_from_family.get(family, 0))
        # Réduction → multiplicateur < 1
        return max(0.05, 1.0 - pct / 100)


class TitleBonusService:
    def aggregate(self, titles: list[TitleDefinition]) -> TitleBonuses:
        bonuses = TitleBonuses()
        for title in titles:
            for effect in title.effects:
                etype = effect.get("type")
                target = effect.get("target", "")
                value = int(effect.get("value", 0))
                if not target or value <= 0:
                    continue
                if etype == "damage_bonus_vs_family":
                    bonuses.damage_bonus_vs_family[target] = (
                        bonuses.damage_bonus_vs_family.get(target, 0) + value
                    )
                elif etype == "damage_reduction_from_family":
                    bonuses.damage_reduction_from_family[target] = (
                        bonuses.damage_reduction_from_family.get(target, 0) + value
                    )
                # Type inconnu : ignoré poliment (extensibilité)
        return bonuses
