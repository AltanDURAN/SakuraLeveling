"""Offrande commune (`/offrande`) — règles pures (27/10/2026, idée de l'auteur).

Tout le serveur verse de l'or dans une JAUGE commune. Pleine, elle invoque
une DIVINITÉ tirée au hasard dans `deities.json` (jamais deux fois de suite),
qui bénit tout le serveur pendant `BLESSING_HOURS` heures. La jauge ne se
remplit qu'UNE fois par jour (minuit, heure de Paris) ; l'or versé qui ne la
remplit pas reste dedans pour le lendemain.

Prix : chaque remplissage rend la suivante plus chère (× `GROWTH`) ; chaque
jour SANS remplissage la fait redescendre (× `DECAY`, jamais sous `BASE`).
Le prix suit donc tout seul ce que le serveur peut payer — c'est un puits
d'or pour la fin de partie (le surplus mesuré : 1,5 à 2,3 M par joueur au
bout d'un an), qui ne devient jamais inaccessible.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

BASE_TARGET = 25_000
GROWTH = 1.08
DECAY = 0.95
ROUND_TO = 500
BLESSING_HOURS = 24

#: Effets connus du code (une divinité en porte un) :
EFFECTS = {
    "gold_pct",         # +X % d'or en combat de zone
    "xp_pct",           # +X % d'XP en combat de zone
    "gear_drop_pct",    # +X % de chances de pièce (bridé comme les autres bonus de butin)
    "regen_mult",       # régénération hors combat ×X
    "essence_bonus",    # +X essences par victoire
    "pack_chance_pct",  # part des apparitions de zone qui sont des meutes
    "tower_tickets",    # +X tickets de tour par jour
}


@dataclass(frozen=True)
class Deity:
    code: str
    name: str
    title: str
    emoji: str
    effect: str
    value: float
    blessing: str

    @property
    def label(self) -> str:
        return f"{self.emoji} {self.name}, {self.title}"


def _round(value: float) -> int:
    return max(ROUND_TO, int(round(value / ROUND_TO)) * ROUND_TO)


def grown(target: int) -> int:
    """Prix de la jauge suivante après un remplissage."""
    return _round(target * GROWTH)


def decayed(target: int, days_without_fill: int) -> int:
    """Prix après `days_without_fill` jours sans remplissage (jamais sous BASE)."""
    value = float(target)
    for _ in range(max(0, days_without_fill)):
        value = max(BASE_TARGET, value * DECAY)
    return max(BASE_TARGET, _round(value))


def pick_deity(deities: list[Deity], last_code: str | None = None,
               rng: random.Random | None = None) -> Deity | None:
    """Une divinité au hasard, pas la même que la dernière fois."""
    pool = [d for d in deities if d.code != last_code] or list(deities)
    return (rng or random).choice(pool) if pool else None


def effect_value(deity: Deity | None, effect: str) -> float:
    """Ampleur de `effect` si la divinité active le porte, sinon 0."""
    return deity.value if deity is not None and deity.effect == effect else 0.0
