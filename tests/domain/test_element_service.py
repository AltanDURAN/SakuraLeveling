"""Tests du système élémentaire (graphe + formule de dégâts ±50%)."""

import pytest

from app.domain.services import element_service as es
from app.shared.enums import ALL_ELEMENTS, Element


def test_graph_is_consistent_beats_and_beaten_by_are_inverse():
    for e in ALL_ELEMENTS:
        for target in es.BEATS[e]:
            assert e in es.BEATEN_BY[target]
    for e in ALL_ELEMENTS:
        for attacker in es.BEATEN_BY[e]:
            assert e in es.BEATS[attacker]


def test_base_cycle_relations():
    assert es.relation(Element.EAU, Element.FEU) == "advantage"
    assert es.relation(Element.FEU, Element.PLANTE) == "advantage"
    assert es.relation(Element.PLANTE, Element.EAU) == "advantage"
    # inverse = désavantage
    assert es.relation(Element.FEU, Element.EAU) == "disadvantage"
    # sans relation directe
    assert es.relation(Element.LUMIERE, Element.FEU) == "neutral"


def test_light_dark_oppose_each_other():
    assert es.relation(Element.LUMIERE, Element.TENEBRE) == "advantage"
    assert es.relation(Element.TENEBRE, Element.LUMIERE) == "advantage"


def test_user_example_score_equals_100():
    # Exemple de la spec : feu 100 vs cible feu20 / terre10 / vent10 / glace40.
    # terre et vent battent feu (−), glace est battu par feu (+).
    attacker = {Element.FEU.value: 100}
    defender = {
        Element.FEU.value: 20,
        Element.TERRE.value: 10,
        Element.VENT.value: 10,
        Element.GLACE.value: 40,
    }
    score = es.elemental_score(Element.FEU, attacker, defender)
    assert score == 100 - 20 - 10 - 10 + 40  # == 100


def test_multiplier_is_bounded_to_default_magnitude():
    # Score très positif → +magnitude max (défaut ±30%).
    attacker = {Element.FEU.value: 100}
    weak_defender = es.single_element_affinities(Element.GLACE)  # feu bat glace
    mult_max = es.damage_multiplier(Element.FEU, attacker, weak_defender)
    assert mult_max == pytest.approx(1.0 + es.DEFAULT_MAGNITUDE)

    # Score très négatif → -magnitude max.
    poor_attacker = {Element.FEU.value: 0}
    strong_defender = es.single_element_affinities(Element.EAU)  # eau bat feu
    mult_min = es.damage_multiplier(Element.FEU, poor_attacker, strong_defender)
    assert mult_min == pytest.approx(1.0 - es.DEFAULT_MAGNITUDE)


def test_neutral_multiplier_when_score_zero():
    # Attaquant 0 d'affinité, cible sans aucun élément pertinent → score 0.
    mult = es.damage_multiplier(Element.FEU, {}, {})
    assert mult == pytest.approx(1.0)


def test_single_element_affinities_shape():
    aff = es.single_element_affinities(Element.TENEBRE)
    assert aff[Element.TENEBRE.value] == 100
    assert sum(v for k, v in aff.items() if k != Element.TENEBRE.value) == 0


def test_weaknesses_and_resistances_of_boss():
    # Le feu est battu par eau / vent / terre.
    assert set(es.weaknesses_of(Element.FEU)) == {Element.EAU, Element.VENT, Element.TERRE}
    # Le feu bat plante / glace.
    assert set(es.resistances_of(Element.FEU)) == {Element.PLANTE, Element.GLACE}


def test_attacking_boss_with_its_weakness_gives_bonus():
    # Boss feu : attaquer avec eau (qui bat feu) avec forte affinité → bonus.
    boss = es.single_element_affinities(Element.FEU)
    attacker = {Element.EAU.value: 100}
    mult = es.damage_multiplier(Element.EAU, attacker, boss)
    assert mult > 1.0
