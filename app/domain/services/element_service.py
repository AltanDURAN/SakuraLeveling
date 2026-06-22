"""Service métier pur du système élémentaire.

Graphe de forces (qui bat qui), formule d'avantage élémentaire et conversion
en multiplicateur de dégâts. Aucune dépendance DB/Discord : entièrement testable.

Cycle (d'après la spec) :
  eau > feu, feu > plante, plante > eau            (cycle de base)
  feu > glace, glace > eau, glace > plante
  eau > vent, vent > feu, vent > plante
  plante > terre, terre > feu, terre > eau
  lumiere <-> tenebre                              (opposition mutuelle)
"""

from __future__ import annotations

from app.shared.enums import ALL_ELEMENTS, Element


# element -> éléments qu'il BAT (avantage offensif).
BEATS: dict[Element, frozenset[Element]] = {
    Element.FEU:     frozenset({Element.PLANTE, Element.GLACE}),
    Element.EAU:     frozenset({Element.FEU, Element.VENT}),
    Element.PLANTE:  frozenset({Element.EAU, Element.TERRE}),
    Element.GLACE:   frozenset({Element.EAU, Element.PLANTE}),
    Element.VENT:    frozenset({Element.FEU, Element.PLANTE}),
    Element.TERRE:   frozenset({Element.FEU, Element.EAU}),
    Element.LUMIERE: frozenset({Element.TENEBRE}),
    Element.TENEBRE: frozenset({Element.LUMIERE}),
}

# element -> éléments qui LE battent (calculé comme l'inverse de BEATS).
BEATEN_BY: dict[Element, frozenset[Element]] = {
    e: frozenset(x for x in ALL_ELEMENTS if e in BEATS.get(x, frozenset()))
    for e in ALL_ELEMENTS
}

# Amplitude maximale de l'avantage élémentaire : ±30% des dégâts.
# (Assez fort pour récompenser un build adapté à l'élément de l'ennemi, sans
# écraser le reste — un mauvais matchup reste jouable.)
DEFAULT_MAGNITUDE: float = 0.3


def _coerce(element: str | Element) -> Element:
    return element if isinstance(element, Element) else Element(element)


def _aff(affinities: dict, element: Element) -> int:
    """Lit l'affinité d'un élément dans un dict (clés str ou Element). Défaut 0."""
    if element in affinities:
        return int(affinities[element])
    if element.value in affinities:
        return int(affinities[element.value])
    return 0


def single_element_affinities(element: str | Element) -> dict[str, int]:
    """Profil d'affinités d'une cible MONO-élément (boss/mob) : 100 sur son
    élément, 0 ailleurs. Permet d'appliquer la même formule qu'entre joueurs."""
    elem = _coerce(element)
    return {e.value: (100 if e == elem else 0) for e in ALL_ELEMENTS}


def elemental_score(
    attack_element: str | Element,
    attacker_affinities: dict,
    defender_affinities: dict,
) -> int:
    """Score élémentaire (spec joueur) quand on attaque avec `attack_element` :

        score = aff_attaquant(E)
                − aff_cible(E)                       (résistance même élément)
                − Σ aff_cible(X) pour X qui bat E    (contre-éléments de la cible)
                + Σ aff_cible(Y) pour Y battu par E  (éléments faibles à E chez la cible)

    Non borné ici ; le clamp se fait à la conversion en multiplicateur.
    """
    e = _coerce(attack_element)

    score = _aff(attacker_affinities, e)
    score -= _aff(defender_affinities, e)
    score -= sum(_aff(defender_affinities, x) for x in BEATEN_BY[e])
    score += sum(_aff(defender_affinities, y) for y in BEATS[e])
    return score


def damage_multiplier(
    attack_element: str | Element,
    attacker_affinities: dict,
    defender_affinities: dict,
    magnitude: float = DEFAULT_MAGNITUDE,
) -> float:
    """Multiplicateur de dégâts élémentaire dans [1-magnitude, 1+magnitude].

    Le score (clampé à ±100) est mappé linéairement : +100 → +magnitude,
    -100 → -magnitude, 0 → neutre (×1.0).
    """
    score = elemental_score(attack_element, attacker_affinities, defender_affinities)
    clamped = max(-100, min(100, score))
    return 1.0 + (clamped / 100.0) * magnitude


def relation(attack_element: str | Element, defender_element: str | Element) -> str:
    """Relation simple attaquant→cible MONO-élément (pour affichage) :
    'advantage' si l'attaquant bat la cible, 'disadvantage' si la cible bat
    l'attaquant, 'neutral' sinon."""
    a = _coerce(attack_element)
    d = _coerce(defender_element)
    if d in BEATS[a]:
        return "advantage"
    if a in BEATS[d]:
        return "disadvantage"
    return "neutral"


def weaknesses_of(defender_element: str | Element) -> list[Element]:
    """Éléments auxquels une cible mono-élément est FAIBLE (qui la battent).
    Sert à afficher la 'faiblesse' d'un boss."""
    return sorted(BEATEN_BY[_coerce(defender_element)], key=lambda e: e.value)


def resistances_of(defender_element: str | Element) -> list[Element]:
    """Éléments que la cible mono-élément bat (donc résiste à leur avantage)."""
    return sorted(BEATS[_coerce(defender_element)], key=lambda e: e.value)
