"""Événements lunaires des zones (30/10/2026, idée de l'auteur), calés sur le
VRAI ciel de Paris (`astronomy`) :

  🌕 PLEINE LUNE — la nuit de la pleine lune (coucher → lever du Soleil ; si
     la pleine lune tombe de jour, la nuit la plus proche) : les monstres qui
     apparaissent dans les zones sont 2× plus forts (PV et ATK), mais
     rapportent 3× plus (XP, or, chances de butin et de pièce).
  🩸 LUNE DE SANG — une pleine lune sur trois (numéro de lunaison multiple
     de 3) : 3× plus forts, 5× plus de gains, et ils apparaissent 2× plus
     souvent.
  🌑 NUIT NOIRE — la nuit de la nouvelle lune : sans clair de lune, les
     énergies élémentaires affleurent — 3× plus d'essences, monstres
     inchangés (proposition, pour que la nouvelle lune compte aussi).
  🌘 LUNE DÉVORÉE — une éclipse de Lune VISIBLE de Paris, le temps qu'elle
     dure : 3× plus forts, 6× plus de gains, 2× plus d'essences, 2× plus
     souvent. La plus rare (une à deux par an).
  🌞 SOLEIL NOIR — une éclipse de Soleil visible de Paris, le temps qu'elle
     dure (de jour) : 2× plus forts, 4× plus de gains, 2× plus d'essences,
     2× plus souvent.

Une seule à la fois : l'éclipse l'emporte sur la lune de sang, qui l'emporte
sur la pleine lune. Les multiplicateurs se règlent depuis l'admin (Monde ›
Rythme) ; le ciel, lui, ne se règle pas.

La DÉFENSE des monstres n'est jamais multipliée : au-delà de l'attaque des
joueurs, elle ne laisserait que le plancher de dégâts (cf. CLAUDE.md, piège
de la saison 1).
"""

from __future__ import annotations

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
    strength: float = 1.0       # PV et ATK des monstres
    rewards: float = 1.0        # XP, or, chances de butin et de pièce
    essences: float = 1.0
    spawn_rate: float = 1.0     # apparitions (2 = délai divisé par deux)


@dataclass(frozen=True)
class LunarKind:
    code: str
    name: str
    emoji: str
    priority: int
    story: str


KINDS: dict[str, LunarKind] = {k.code: k for k in (
    LunarKind("eclipse_lunaire", "Lune dévorée", "🌘", 5,
              "L'ombre de la Terre dévore la Lune : les monstres deviennent fous."),
    LunarKind("eclipse_solaire", "Soleil noir", "🌞", 4,
              "La Lune masque le Soleil en plein jour : les créatures de la nuit sortent."),
    LunarKind("lune_de_sang", "Lune de sang", "🩸", 3,
              "Une lune rouge se lève : les monstres sont plus nombreux et enragés."),
    LunarKind("pleine_lune", "Pleine lune", "🌕", 2,
              "Sous la pleine lune, les monstres sont plus forts… et plus riches."),
    LunarKind("nouvelle_lune", "Nuit noire", "🌑", 1,
              "Sans lune, les énergies élémentaires affleurent."),
)}

DEFAULT_RULES: dict[str, LunarRule] = {
    "pleine_lune": LunarRule(strength=2.0, rewards=3.0),
    "lune_de_sang": LunarRule(strength=3.0, rewards=5.0, spawn_rate=2.0),
    "nouvelle_lune": LunarRule(essences=3.0),
    "eclipse_lunaire": LunarRule(strength=3.0, rewards=6.0, essences=2.0, spawn_rate=2.0),
    "eclipse_solaire": LunarRule(strength=2.0, rewards=4.0, essences=2.0, spawn_rate=2.0),
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
    """« monstres ×2 plus forts · gains ×3 » (rien pour un effet neutre)."""
    parts = []
    if rule.strength != 1:
        parts.append(f"monstres ×{rule.strength:g} plus forts")
    if rule.rewards != 1:
        parts.append(f"XP, or et butin ×{rule.rewards:g}")
    if rule.essences != 1:
        parts.append(f"essences ×{rule.essences:g}")
    if rule.spawn_rate != 1:
        parts.append(f"apparitions ×{rule.spawn_rate:g}")
    return " · ".join(parts) or "aucun effet"


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
        if not 1 <= rule.strength <= 10:
            errors.append(f"{name} : la force des monstres va de ×1 à ×10.")
        if not 1 <= rule.rewards <= 20 or not 1 <= rule.essences <= 20:
            errors.append(f"{name} : les gains vont de ×1 à ×20.")
        if not 1 <= rule.spawn_rate <= 10:
            errors.append(f"{name} : les apparitions vont de ×1 à ×10.")
    return errors
