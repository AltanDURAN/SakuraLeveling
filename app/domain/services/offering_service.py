"""Offrande commune (`/offrande`) — règles pures (27/10/2026, idée de l'auteur).

Tout le serveur verse de l'or dans une JAUGE commune. Pleine, elle invoque
une DIVINITÉ tirée au hasard dans `offering.json` (jamais deux fois de
suite), qui bénit tout le serveur pendant `blessing_hours` heures. La jauge ne se
remplit qu'UNE fois par jour (minuit, heure de Paris). Rien ne se perd : l'or
versé qui ne la remplit pas reste dedans, le DÉPASSEMENT passe dans la
jauge suivante, et on peut verser même quand la jauge du jour est exaucée
(ça prépare la suivante, qui se déclenche dès minuit si elle est pleine).

Prix (formule de l'auteur, 27/10/2026) : départ `base_target` 1 500 ; à
chaque remplissage, prix suivant = (prix + `step_per_fill` × jauges
remplies depuis le début) × (1 + `growth_pct` %) ; chaque jour SANS
remplissage, × (1 − `decay_pct` %) (jamais sous le départ). Les paramètres
vivent dans `offering.json` et se règlent depuis l'admin web (`OfferingParams`). Simulé, en remplissant tous les jours : 4 300 à J7,
60 000 à J30, 380 000 à J60 — le serveur ne suit plus et le prix se cale
alors tout seul vers ~3 jours de dons du serveur (une bénédiction tous les
~3 jours ; le terme × n la rend un peu plus rare au fil de la saison). C'est
un puits d'or pour la fin de partie (surplus mesuré : 1,5 à 2,3 M par joueur
au bout d'un an) qui ne devient jamais inaccessible.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

@dataclass(frozen=True)
class OfferingParams:
    base_target: int = 1_500        # prix de la première jauge (et plancher)
    step_per_fill: int = 75         # + X or × jauges remplies depuis le début
    growth_pct: float = 4.0         # + % à chaque remplissage
    decay_pct: float = 2.0          # − % par jour sans remplissage
    blessing_hours: int = 24        # durée de la bénédiction


DEFAULT_PARAMS = OfferingParams()
BASE_TARGET = DEFAULT_PARAMS.base_target

#: Effets connus du code (une divinité en porte un), avec leur libellé pour
#: l'admin. Pas d'or : l'offrande est un puits d'or (décision de l'auteur).
EFFECT_LABELS: dict[str, str] = {
    "xp_pct": "+X % d'XP en combat de zone",
    "material_bonus": "+X matériaux de fusion par victoire (quand le butin tombe)",
    "gear_drop_pct": "+X % de chances de pièce, commun → épique (bridé comme les autres bonus)",
    "regen_mult": "régénération des PV et du mana hors combat ×X",
    "essence_bonus": "+X essences élémentaires par victoire",
    "pack_chance_pct": "X % des apparitions de zone sont des meutes",
    "tower_tickets": "+X tickets de tour par jour",
}
EFFECTS = set(EFFECT_LABELS)


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


def grown(target: int, fills: int, params: OfferingParams = DEFAULT_PARAMS) -> int:
    """Prix de la jauge suivante après le remplissage n° `fills` (depuis le début)."""
    return round((target + params.step_per_fill * fills) * (1 + params.growth_pct / 100))


def decayed(target: int, days_without_fill: int, params: OfferingParams = DEFAULT_PARAMS) -> int:
    """Prix après `days_without_fill` jours sans remplissage (jamais sous le départ)."""
    value = float(target)
    for _ in range(max(0, days_without_fill)):
        value = max(params.base_target, value * (1 - params.decay_pct / 100))
    return max(params.base_target, round(value))


def simulate_daily(params: OfferingParams, days: int) -> list[tuple[int, int, int]]:
    """Si le serveur remplit la jauge CHAQUE jour : [(jour, prix de la jauge
    de ce jour, or versé au total)] — l'aperçu de l'admin."""
    out, target, total = [], params.base_target, 0
    for day in range(1, days + 1):
        out.append((day, target, total + target))
        total += target
        target = grown(target, day, params)
    return out


def validate_params(params: OfferingParams) -> list[str]:
    """Erreurs de saisie (vide = paramètres valides)."""
    errors = []
    if params.base_target < 1:
        errors.append("Le prix de départ doit être d'au moins 1 or.")
    if params.step_per_fill < 0:
        errors.append("L'ajout par jauge remplie ne peut pas être négatif.")
    if not 0 <= params.growth_pct <= 100:
        errors.append("La hausse par remplissage doit être entre 0 et 100 %.")
    if not 0 <= params.decay_pct < 100:
        errors.append("La baisse par jour sans remplissage doit être entre 0 et 99 %.")
    if not 1 <= params.blessing_hours <= 168:
        errors.append("La bénédiction dure entre 1 et 168 heures.")
    return errors


def pick_deity(deities: list[Deity], last_code: str | None = None,
               rng: random.Random | None = None) -> Deity | None:
    """Une divinité au hasard, pas la même que la dernière fois."""
    pool = [d for d in deities if d.code != last_code] or list(deities)
    return (rng or random).choice(pool) if pool else None


def effect_value(deity: Deity | None, effect: str) -> float:
    """Ampleur de `effect` si la divinité active le porte, sinon 0."""
    return deity.value if deity is not None and deity.effect == effect else 0.0
