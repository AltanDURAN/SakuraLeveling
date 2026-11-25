"""Événements lunaires des zones (30/10/2026, idée de l'auteur), calés sur le
VRAI ciel de Paris (`astronomy`) :

  🌕 PLEINE LUNE — la nuit de la pleine lune (coucher → lever du Soleil ; si
     la pleine lune tombe de jour, la nuit la plus proche) : les monstres qui
     apparaissent dans les zones ont une PUISSANCE ×3, mais rapportent 3×
     plus (XP, or, chances de butin et de pièce).
  🩸 LUNE DE SANG — une pleine lune sur trois (numéro de lunaison multiple
     de 3) : puissance ×6, 5× plus de gains, et ils apparaissent 2× plus
     souvent.
  🌑 NOUVELLE LUNE — la nuit de la nouvelle lune : monstres inchangés, mais
     ceux de type TÉNÈBRE apparaissent 2× plus souvent et les essences ×3.
  🌘 ÉCLIPSE LUNAIRE — une éclipse de Lune VISIBLE de Paris, le temps
     qu'elle dure : puissance ×10, 6× plus de gains, essences ×5,
     apparitions ×2. La plus rare (une à deux par an).
  🌞 ÉCLIPSE SOLAIRE — une éclipse de Soleil visible de Paris, le temps
     qu'elle dure (de jour) : puissance ×15, 10× plus de gains, essences ×10,
     apparitions ×3.
  (Valeurs de l'auteur, 30/10/2026.)

⚠️ PUISSANCE (25/11/2026, retour des testeurs, décision de l'auteur) : le
multiplicateur annoncé est celui du SCORE DE PUISSANCE affiché sur le
monstre, pas celui de ses PV et de son ATK. Avant, « ×2 plus forts »
doublait PV et ATK, ce qui faisait ~×3 sur le score (attaque × PV
effectifs) : les joueurs lisaient ×2 et voyaient ×3. `stat_factor` calcule
pour chaque monstre le facteur de PV et d'ATK qui donne exactement ce
score. Les valeurs ont été relabellisées à difficulté CONSTANTE : ×2 / ×3 /
×4 / ×5 sur PV et ATK = puissance ×3 / ×6 / ×10 / ×15 en moyenne.

Une seule à la fois : l'éclipse l'emporte sur la lune de sang, qui l'emporte
sur la pleine lune. Les multiplicateurs se règlent depuis l'admin (Monde ›
Rythme) ; le ciel, lui, ne se règle pas.

La puissance monte par les PV et l'ATK. La DÉFENSE a son propre réglage (×1 par défaut) :
même si 25 % de l'attaque passe toujours (formule unique), une défense
au-delà de 75 % de l'ATK d'un joueur lui RENVOIE la différence en contrecoup
à chaque coup — ×3 sur la défense, c'est des joueurs qui se blessent plus
qu'ils ne blessent.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from functools import lru_cache

from app.domain.services import astronomy

#: Une pleine lune sur `BLOOD_MOON_EVERY` est une lune de sang.
BLOOD_MOON_EVERY = 3


@dataclass(frozen=True)
class LunarRule:
    """Effet d'un événement sur les zones (réglable dans l'admin)."""
    enabled: bool = True
    strength: float = 1.0       # PUISSANCE des monstres (score affiché ×N)
    rewards: float = 1.0        # XP, or, chances de butin et de pièce
    essences: float = 1.0
    spawn_rate: float = 1.0     # apparitions (2 = délai divisé par deux)
    defense: float = 1.0        # DÉFENSE des monstres (à part : cf. plus haut)
    element: str = ""           # élément favorisé à l'apparition…
    element_weight: float = 1.0  # …avec ce poids (2 = deux fois plus souvent)


@dataclass(frozen=True)
class LunarKind:
    code: str
    name: str
    emoji: str
    priority: int
    story: str


KINDS: dict[str, LunarKind] = {k.code: k for k in (
    LunarKind("eclipse_lunaire", "Éclipse lunaire", "🌘", 5,
              "L'ombre de la Terre dévore la Lune : les monstres deviennent fous."),
    LunarKind("eclipse_solaire", "Éclipse solaire", "🌞", 4,
              "La Lune masque le Soleil en plein jour : les créatures de la nuit sortent."),
    LunarKind("lune_de_sang", "Lune de sang", "🩸", 3,
              "Une lune rouge se lève : les monstres sont plus nombreux et enragés."),
    LunarKind("pleine_lune", "Pleine lune", "🌕", 2,
              "Sous la pleine lune, les monstres sont plus forts… et plus riches."),
    LunarKind("nouvelle_lune", "Nouvelle lune", "🌑", 1,
              "Sans lune, les ténèbres rôdent et les énergies élémentaires affleurent."),
)}

DEFAULT_RULES: dict[str, LunarRule] = {
    "pleine_lune": LunarRule(strength=3.0, rewards=3.0),
    "lune_de_sang": LunarRule(strength=6.0, rewards=5.0, spawn_rate=2.0),
    "nouvelle_lune": LunarRule(essences=3.0, element="tenebre", element_weight=2.0),
    "eclipse_lunaire": LunarRule(strength=10.0, rewards=6.0, essences=5.0, spawn_rate=2.0),
    "eclipse_solaire": LunarRule(strength=15.0, rewards=10.0, essences=10.0, spawn_rate=3.0),
}


@dataclass(frozen=True)
class LunarEvent:
    code: str
    start: datetime
    end: datetime
    detail: str = ""             # ex. « éclipse partielle, 93 % »
    rule: LunarRule = LunarRule()

    @property
    def kind(self) -> LunarKind:
        return KINDS[self.code]

    @property
    def label(self) -> str:
        return f"{self.kind.emoji} {self.kind.name}"

    def active(self, when: datetime) -> bool:
        return self.start <= when < self.end


def is_blood_moon(k: int) -> bool:
    return k % BLOOD_MOON_EVERY == 0


@lru_cache(maxsize=256)
def _sky_events(k: int) -> tuple[LunarEvent, ...]:
    """Les événements du ciel de la lunaison k (sans règle de jeu) : la
    nuit de nouvelle lune, celle de pleine lune, et les éclipses visibles."""
    out = []
    start, end = astronomy.night_around(astronomy.new_moon(k))
    out.append(LunarEvent("nouvelle_lune", start, end))
    start, end = astronomy.night_around(astronomy.full_moon(k))
    out.append(LunarEvent("lune_de_sang" if is_blood_moon(k) else "pleine_lune", start, end))
    for eclipse, code in ((astronomy.lunar_eclipse(k), "eclipse_lunaire"),
                          (astronomy.solar_eclipse(k), "eclipse_solaire")):
        if eclipse is not None:
            nature = "totale" if eclipse.total else "partielle"
            detail = f"éclipse {nature}, {min(100, round(eclipse.magnitude * 100))} %"
            if code == "eclipse_lunaire" and eclipse.total:
                detail = "éclipse totale"
            out.append(LunarEvent(code, eclipse.start, eclipse.end, detail))
    return tuple(out)


def events_between(start: datetime, end: datetime,
                   rules: dict[str, LunarRule] | None = None) -> list[LunarEvent]:
    """Les événements ACTIFS (règle activée) qui chevauchent [start, end[,
    dans l'ordre chronologique, avec leur règle."""
    rules = {**DEFAULT_RULES, **(rules or {})}
    k0 = astronomy.lunation(start) - 1
    k1 = astronomy.lunation(end) + 1
    out = []
    for k in range(k0, k1 + 1):
        for event in _sky_events(k):
            rule = rules.get(event.code, LunarRule())
            if rule.enabled and event.end > start and event.start < end:
                out.append(replace(event, rule=rule))
    return sorted(out, key=lambda e: (e.start, -e.kind.priority))


def active_event(when: datetime, rules: dict[str, LunarRule] | None = None) -> LunarEvent | None:
    """L'événement en cours à `when` (le plus fort si plusieurs se chevauchent)."""
    current = [e for e in events_between(when - timedelta(days=2), when + timedelta(days=2), rules)
               if e.active(when)]
    return max(current, key=lambda e: e.kind.priority) if current else None


def upcoming(when: datetime, rules: dict[str, LunarRule] | None = None,
             days: int = 400) -> list[LunarEvent]:
    """Les événements à venir (ou en cours) sur `days` jours."""
    return [e for e in events_between(when, when + timedelta(days=days), rules) if e.end > when]


def effects_text(rule: LunarRule) -> str:
    """« puissance des monstres ×3 · gains ×3 » (rien pour un effet neutre)."""
    parts = []
    if rule.strength != 1:
        parts.append(f"puissance des monstres ×{rule.strength:g}")
    if rule.defense != 1:
        parts.append(f"défense ×{rule.defense:g}")
    if rule.element and rule.element_weight != 1:
        from app.shared.enums import ELEMENT_LABELS

        label = ELEMENT_LABELS.get(rule.element, rule.element).lower()
        parts.append(f"monstres {label} ×{rule.element_weight:g} plus fréquents")
    if rule.rewards != 1:
        parts.append(f"XP, or et butin ×{rule.rewards:g}")
    if rule.essences != 1:
        parts.append(f"essences ×{rule.essences:g}")
    if rule.spawn_rate != 1:
        parts.append(f"apparitions ×{rule.spawn_rate:g}")
    return " · ".join(parts) or "aucun effet"


def stat_factor(max_hp: float, defense: float, power: float,
                defense_factor: float = 1.0) -> float:
    """Facteur à appliquer aux PV ET à l'ATK d'un monstre (dont la défense est
    multipliée par `defense_factor`) pour que son SCORE DE PUISSANCE soit
    exactement `power` × son score normal.

    Score ∝ ATK × (PV + DEF × k) (`PowerScoreService`, k = PV par point de
    défense) ; ×f sur PV et ATK : f² × PV + f × DEF' × k = power × (PV + DEF × k),
    une équation du second degré. Si la défense seule suffit déjà, 1.
    """
    from app.domain.services.power_score_service import _DEF_EFFECTIVE_HITS as k

    if power <= 1 and defense_factor <= 1:
        return 1.0
    hp = max(1.0, float(max_hp))
    b = defense * defense_factor * k
    target = power * (hp + defense * k)
    f = (-b + math.sqrt(b * b + 4 * hp * target)) / (2 * hp)
    return max(1.0, f)


def fit_power(score_at, power: float, guess: float) -> float:
    """Affine `guess` (de `stat_factor`) sur le VRAI score, stats arrondies
    comprises : `score_at(f)` = score affiché du monstre avec PV et ATK × f.
    Sur un petit monstre (ATK 8, score 37), l'arrondi seul faisait ×15,8 au
    lieu de ×15. Dichotomie : le score croît avec f."""
    base = score_at(1.0)
    target = power * base
    if power <= 1:
        return guess
    lo, hi = 1.0, max(guess * 2, 2.0)
    best = min((guess, lo), key=lambda f: abs(score_at(f) - target))
    for _ in range(40):
        mid = (lo + hi) / 2
        value = score_at(mid)
        if abs(value - target) < abs(score_at(best) - target):
            best = mid
        if value < target:
            lo = mid
        else:
            hi = mid
    return best


def element_boost(rule: LunarRule) -> dict[str, float]:
    """{élément: poids} à appliquer au tirage de l'élément d'un monstre."""
    return {rule.element: rule.element_weight} if rule.element and rule.element_weight != 1 else {}


def phase_emoji(fraction: float) -> str:
    """🌑🌒🌓🌔🌕🌖🌗🌘 selon l'âge de la lune (0 = nouvelle, 0,5 = pleine)."""
    return "🌑🌒🌓🌔🌕🌖🌗🌘"[int((fraction * 8 + 0.5) % 8)]


def phase_name(fraction: float) -> str:
    names = ("Nouvelle lune", "Premier croissant", "Premier quartier", "Lune gibbeuse croissante",
             "Pleine lune", "Lune gibbeuse décroissante", "Dernier quartier", "Dernier croissant")
    return names[int((fraction * 8 + 0.5) % 8)]


def validate(rules: dict[str, LunarRule]) -> list[str]:
    errors = []
    for code, rule in rules.items():
        name = KINDS[code].name if code in KINDS else code
        if not 1 <= rule.strength <= 50:
            errors.append(f"{name} : la puissance des monstres va de ×1 à ×50.")
        if not 1 <= rule.rewards <= 20 or not 1 <= rule.essences <= 20:
            errors.append(f"{name} : les gains vont de ×1 à ×20.")
        if not 1 <= rule.spawn_rate <= 10 or not 1 <= rule.element_weight <= 10:
            errors.append(f"{name} : les apparitions vont de ×1 à ×10.")
        if not 1 <= rule.defense <= 10:
            errors.append(f"{name} : la défense des monstres va de ×1 à ×10.")
        if rule.element:
            from app.shared.enums import ALL_ELEMENTS

            if rule.element not in {e.value for e in ALL_ELEMENTS}:
                errors.append(f"{name} : élément inconnu « {rule.element} ».")
    return errors
