"""Offrande commune (`/offrande`) — règles pures (27/10/2026, idée de l'auteur).

Tout le serveur verse de l'or dans une JAUGE commune. Pleine, elle invoque
une DIVINITÉ tirée au hasard dans `deities.json` (jamais deux fois de suite),
qui bénit tout le serveur pendant `BLESSING_HOURS` heures. La jauge ne se
remplit qu'UNE fois par jour (minuit, heure de Paris). Rien ne se perd : l'or
versé qui ne la remplit pas reste dedans, le DÉPASSEMENT passe dans la
jauge suivante, et on peut verser même quand la jauge du jour est exaucée
(ça prépare la suivante, qui se déclenche dès minuit si elle est pleine).

Prix (formule de l'auteur, 27/10/2026) : départ `BASE_TARGET` 1 500 ; à
chaque remplissage, prix suivant = (prix + `STEP_PER_FILL` × jauges remplies
depuis le début) × `GROWTH` ; chaque jour SANS remplissage, × `DECAY`
(jamais sous la base). Simulé, en remplissant tous les jours : 4 300 à J7,
60 000 à J30, 380 000 à J60 — le serveur ne suit plus et le prix se cale
alors tout seul vers ~3 jours de dons du serveur (une bénédiction tous les
~3 jours ; le terme × n la rend un peu plus rare au fil de la saison). C'est
un puits d'or pour la fin de partie (surplus mesuré : 1,5 à 2,3 M par joueur
au bout d'un an) qui ne devient jamais inaccessible.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

BASE_TARGET = 1_500
STEP_PER_FILL = 75
GROWTH = 1.04
DECAY = 0.98
BLESSING_HOURS = 24

#: Effets connus du code (une divinité en porte un). Pas d'or : l'offrande
#: est un puits d'or (décision de l'auteur).
EFFECTS = {
    "xp_pct",           # +X % d'XP en combat de zone
    "material_bonus",   # +X matériaux de fusion par victoire (quand le butin tombe)
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


def grown(target: int, fills: int) -> int:
    """Prix de la jauge suivante après le remplissage n° `fills` (depuis le début)."""
    return round((target + STEP_PER_FILL * fills) * GROWTH)


def decayed(target: int, days_without_fill: int) -> int:
    """Prix après `days_without_fill` jours sans remplissage (jamais sous BASE)."""
    value = float(target)
    for _ in range(max(0, days_without_fill)):
        value = max(BASE_TARGET, value * DECAY)
    return max(BASE_TARGET, round(value))


def pick_deity(deities: list[Deity], last_code: str | None = None,
               rng: random.Random | None = None) -> Deity | None:
    """Une divinité au hasard, pas la même que la dernière fois."""
    pool = [d for d in deities if d.code != last_code] or list(deities)
    return (rng or random).choice(pool) if pool else None


def effect_value(deity: Deity | None, effect: str) -> float:
    """Ampleur de `effect` si la divinité active le porte, sinon 0."""
    return deity.value if deity is not None and deity.effect == effect else 0.0
