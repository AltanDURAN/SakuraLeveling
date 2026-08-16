"""Paliers de contribution au raid hebdomadaire.

Le partage au prorata récompense justement, mais il ne donne pas d'OBJECTIF :
un joueur ne sait pas ce qu'il « vise ». Les paliers rendent l'effort lisible
(« il me manque 3 % pour l'Or »), se montrent sur la bannière de victoire et
dans `/boss`, et valorisent la régularité sur la semaine.

Le palier dépend de la PART de contribution du joueur dans l'effort total du
raid (dégâts + dégâts encaissés + soins, normalisés) — pas d'une valeur absolue,
pour rester juste quel que soit le nombre de participants ou la taille du boss.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ContributionTier:
    code: str
    label: str
    icon: str
    min_share: float      # part minimale de l'effort total (0..1)
    gold_multiplier: float
    bonus_items: tuple[tuple[str, int], ...] = ()

    def format(self) -> str:
        return f"{self.icon} {self.label}"


# Du plus haut au plus bas : le premier atteint gagne.
TIERS: tuple[ContributionTier, ...] = (
    ContributionTier("legende", "Légende du raid", "💎", 0.25, 2.5,
                     (("potion_soin", 3),)),
    ContributionTier("or", "Champion", "🥇", 0.15, 1.8, (("potion_soin", 2),)),
    ContributionTier("argent", "Vétéran", "🥈", 0.05, 1.3, (("potion_soin", 1),)),
    ContributionTier("bronze", "Combattant", "🥉", 0.0, 1.0, ()),
)


def tier_for_share(share: float) -> ContributionTier:
    """Palier atteint pour une part de contribution (0..1)."""
    for tier in TIERS:
        if share >= tier.min_share:
            return tier
    return TIERS[-1]


def next_tier(share: float) -> ContributionTier | None:
    """Palier suivant à viser (None si déjà au sommet) — sert à afficher
    « il vous manque X % pour ... »."""
    current = tier_for_share(share)
    higher = [t for t in TIERS if t.min_share > current.min_share]
    return min(higher, key=lambda t: t.min_share) if higher else None


def share_to_next(share: float) -> float:
    """Part de contribution manquante pour atteindre le palier suivant."""
    nxt = next_tier(share)
    return max(0.0, nxt.min_share - share) if nxt else 0.0
