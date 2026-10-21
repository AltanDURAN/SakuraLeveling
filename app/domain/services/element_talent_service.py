"""Talents élémentaires — tirés à la création du personnage et à chaque saison.

Règles décidées avec l'auteur (octobre 2026) :

  • Chaque élément reçoit un TALENT entier aléatoire de 0 à 10. Il multiplie le
    gain d'essences de cet élément : +talent × 10 % (10 ⇒ +100 %).
  • Talent 0 = ÉLÉMENT MORT : jamais d'essence, l'affinité reste à 0 pour la
    saison, et l'élément ne peut pas être utilisé en combat.
  • Chaque élément mort donne un TIRAGE BONUS : un élément VIVANT tiré au hasard
    reçoit +10 à +30 de talent, et son plafond d'affinité passe de 100 à
    100 + 100 × (nombre de bonus reçus).
  • Cas extrême — les 8 éléments morts : on récompense l'infortune, chaque
    élément reçoit 50 de talent et un plafond de 300.
  • Tout le monde démarre à 0 d'affinité ; seul le RYTHME de progression change.

Le talent est caché au joueur : il le découvre élément par élément avec un
lecture de la voyante (cf. `paper_price`).
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from app.shared.enums import ALL_ELEMENTS

BASE_TALENT_MAX = 10
BONUS_MIN, BONUS_MAX = 10, 30
BASE_CAP = 100
CAP_PER_BOOST = 100
ALL_DEAD_TALENT = 50
ALL_DEAD_CAP = 300


@dataclass(frozen=True)
class ElementTalent:
    talent: int
    boosts: int = 0
    cap: int = BASE_CAP

    @property
    def dead(self) -> bool:
        return self.talent <= 0

    @property
    def essence_bonus_pct(self) -> int:
        return self.talent * 10


def _codes() -> list[str]:
    return [e.value if hasattr(e, "value") else str(e) for e in ALL_ELEMENTS]


def roll_talents(rng: random.Random | None = None) -> dict[str, ElementTalent]:
    """Tirage complet des 8 talents d'un personnage."""
    rng = rng or random
    codes = _codes()
    talents = {code: rng.randint(0, BASE_TALENT_MAX) for code in codes}
    dead = [c for c in codes if talents[c] == 0]
    alive = [c for c in codes if talents[c] > 0]

    if not alive:  # les 8 éléments morts : l'infortune est récompensée
        return {c: ElementTalent(ALL_DEAD_TALENT, 0, ALL_DEAD_CAP) for c in codes}

    boosts = {c: 0 for c in codes}
    for _ in dead:
        lucky = rng.choice(alive)
        talents[lucky] += rng.randint(BONUS_MIN, BONUS_MAX)
        boosts[lucky] += 1
    return {
        c: ElementTalent(talents[c], boosts[c], BASE_CAP + CAP_PER_BOOST * boosts[c])
        for c in codes
    }


def essence_gain(base: int, talent: int, rng: random.Random | None = None) -> int:
    """Essences réellement gagnées : base × (1 + talent × 10 %).

    Pas de décimales stockées : la partie fractionnaire devient une chance
    d'essence en plus (1,3 ⇒ 1, et 2 une fois sur trois). Juste en moyenne.
    Élément mort ⇒ 0.
    """
    if talent <= 0 or base <= 0:
        return 0
    rng = rng or random
    expected = base * (1 + talent / 10)
    whole = int(expected)
    return whole + (1 if rng.random() < expected - whole else 0)


def paper_price(revealed_count: int, prices: list[int]) -> int | None:
    """Prix de la prochaine lecture de la voyante (None = tous les talents connus)."""
    if revealed_count >= len(_codes()):
        return None
    if not prices:
        return 0
    return int(prices[min(revealed_count, len(prices) - 1)])
