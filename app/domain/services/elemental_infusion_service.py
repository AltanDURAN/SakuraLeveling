"""Infusion élémentaire automatique des compétences — SAISON 1.

Les 24 compétences élémentaires équipables ont disparu : toutes les
compétences viennent maintenant de l'arbre, et **l'élément se pose PAR-DESSUS**.

Quand un joueur utilise « Coup Tranchant » contre un monstre faible au feu,
la compétence devient « Coup Tranchant de Feu » et tape plus fort. Le joueur
ne choisit rien : on prend l'élément qui frappe le plus fort CET adversaire,
compte tenu de deux choses —

  • la **faiblesse de la cible** : l'élément qui la bat multiplie les dégâts ;
  • l'**affinité du joueur** dans cet élément : savoir qu'un monstre craint le
    feu ne sert à rien si on ne maîtrise pas le feu.

C'est ce second point qui garde les essences et les affinités utiles : un
joueur qui a monté le feu à 80 infuse réellement ses coups, celui qui l'a
laissé à 3 n'en tire presque rien. L'arbitrage se fait tout seul, à chaque
coup, sans écran de configuration.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.services import element_service
from app.shared.enums import ALL_ELEMENTS, ELEMENT_EMOJIS, ELEMENT_LABELS

#: En dessous de ce gain, l'infusion n'est pas annoncée : afficher
#: « Coup Tranchant de Terre » pour +0,4 % de dégâts serait du bruit.
MIN_MEANINGFUL_GAIN = 0.02

#: Part du bonus de matchup qu'on obtient SANS maîtriser l'élément.
#: ⚠️ Sans ce garde-fou, le score élémentaire sature sur la seule faiblesse de
#: la cible : un joueur qui n'a jamais touché au feu infuserait aussi fort
#: qu'un spécialiste. Savoir qu'un monstre craint le feu ne doit servir à rien
#: si on ne maîtrise pas le feu — c'est ce qui garde les essences utiles.
MIN_MASTERY = 0.15


def mastery_factor(affinity: int) -> float:
    """Part du bonus élémentaire réellement exploitable, selon l'affinité.

    affinité   0 → 15 %      affinité  50 → 57 %      affinité 100 → 100 %
    """
    ratio = max(0, min(100, int(affinity or 0))) / 100.0
    return MIN_MASTERY + (1.0 - MIN_MASTERY) * ratio


@dataclass(frozen=True)
class Infusion:
    """L'élément retenu pour un coup, et ce qu'il rapporte."""

    element: str
    multiplier: float

    @property
    def is_meaningful(self) -> bool:
        return bool(self.element) and self.multiplier >= 1 + MIN_MEANINGFUL_GAIN

    @property
    def label(self) -> str:
        return ELEMENT_LABELS.get(self.element, self.element)

    @property
    def emoji(self) -> str:
        return ELEMENT_EMOJIS.get(self.element, "")

    def name_for(self, skill_name: str) -> str:
        """« Coup Tranchant » → « Coup Tranchant de Feu »."""
        if not self.is_meaningful:
            return skill_name
        return f"{skill_name} de {self.label}"


class ElementalInfusionService:
    def __init__(self, magnitude: float = element_service.DEFAULT_MAGNITUDE) -> None:
        self.magnitude = magnitude

    def best_for(
        self,
        attacker_affinities: dict,
        defender_affinities: dict,
    ) -> Infusion:
        """Élément le plus efficace contre CETTE cible, pour CE joueur.

        On évalue les huit et on garde le meilleur. À égalité, c'est l'élément
        où le joueur a la plus forte affinité qui l'emporte — à efficacité
        égale, autant récompenser ce qu'il a farmé.
        """
        best = Infusion(element="", multiplier=1.0)
        best_affinity = -1

        for element in ALL_ELEMENTS:
            code = element.value if hasattr(element, "value") else str(element)
            affinity = int((attacker_affinities or {}).get(code, 0) or 0)
            raw = element_service.damage_multiplier(
                code, attacker_affinities, defender_affinities, self.magnitude,
            )
            # Le matchup ouvre la porte, la maîtrise décide de ce qu'on en
            # tire. Seuls les GAINS sont pondérés : un mauvais matchup reste
            # mauvais, on se contente de ne pas le choisir.
            gain = max(0.0, raw - 1.0)
            multiplier = 1.0 + gain * mastery_factor(affinity)
            better = multiplier > best.multiplier + 1e-9
            tie_break = (
                abs(multiplier - best.multiplier) <= 1e-9 and affinity > best_affinity
            )
            if better or tie_break:
                best = Infusion(element=code, multiplier=multiplier)
                best_affinity = affinity

        # Aucun élément n'apporte quoi que ce soit : on frappe sans infusion
        # plutôt que d'annoncer un élément décoratif.
        if best.multiplier <= 1.0:
            return Infusion(element="", multiplier=1.0)
        return best
