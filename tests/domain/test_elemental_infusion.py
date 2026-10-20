"""Infusion élémentaire automatique.

Les compétences élémentaires équipables ont disparu : l'élément se pose
par-dessus les compétences de l'arbre, et il est choisi tout seul. Ces tests
verrouillent la règle qui donne du sens aux affinités.
"""

import pytest

from app.domain.services import element_service
from app.domain.services.elemental_infusion_service import (
    MIN_MASTERY,
    ElementalInfusionService,
    mastery_factor,
)

PLANTE = element_service.single_element_affinities("plante")


@pytest.fixture
def svc():
    return ElementalInfusionService()


# ------------------------------------------------------------- maîtrise --
@pytest.mark.parametrize("affinity, attendu", [(0, MIN_MASTERY), (100, 1.0)])
def test_le_facteur_de_maitrise_va_du_plancher_a_un(affinity, attendu):
    assert mastery_factor(affinity) == pytest.approx(attendu)


def test_le_facteur_de_maitrise_est_croissant():
    valeurs = [mastery_factor(a) for a in (0, 20, 40, 60, 80, 100)]
    assert valeurs == sorted(valeurs)


def test_une_affinite_hors_bornes_ne_casse_rien():
    assert mastery_factor(-50) == pytest.approx(MIN_MASTERY)
    assert mastery_factor(9999) == pytest.approx(1.0)


# ---------------------------------------------------------------- choix --
def test_l_element_qui_bat_la_cible_est_choisi(svc):
    """Le feu bat la plante : c'est lui qu'on infuse."""
    assert svc.best_for({"feu": 100}, PLANTE).element == "feu"


def test_LA_regle_savoir_ne_suffit_pas_il_faut_maitriser(svc):
    """Deux joueurs face au MÊME monstre faible au feu : celui qui a monté le
    feu tape bien plus fort. Sans ça, les essences ne serviraient à rien."""
    novice = svc.best_for({}, PLANTE)
    expert = svc.best_for({"feu": 100}, PLANTE)
    assert novice.element == expert.element == "feu"
    assert expert.multiplier > novice.multiplier
    assert expert.multiplier / novice.multiplier > 1.2


def test_une_forte_affinite_peut_l_emporter_sur_le_contre_evident(svc):
    """Avec feu 10 et glace 90, on n'infuse pas le feu par principe : on prend
    ce qui fait réellement le plus de dégâts."""
    choisi = svc.best_for({"feu": 10, "glace": 90}, PLANTE)
    seul_feu = svc.best_for({"feu": 10}, PLANTE)
    assert choisi.multiplier > seul_feu.multiplier


def test_un_element_mort_n_est_jamais_utilise(svc):
    """Talent 0 : l'élément ne peut pas servir en combat, même s'il serait le meilleur."""
    affinities = {e.value: 100 for e in __import__(
        "app.shared.enums", fromlist=["ALL_ELEMENTS"]).ALL_ELEMENTS}
    best = svc.best_for(affinities, PLANTE)
    assert best.element
    assert svc.best_for(affinities, PLANTE, dead_elements={best.element}).element != best.element


def test_aucune_infusion_quand_rien_n_apporte_de_gain(svc):
    """Contre une cible sans faiblesse exploitable et sans affinité, on frappe
    normalement plutôt que d'annoncer un élément décoratif."""
    infusion = svc.best_for({}, {})
    assert infusion.element == ""
    assert infusion.multiplier == 1.0
    assert not infusion.is_meaningful


# -------------------------------------------------------------- nommage --
def test_la_competence_prend_le_nom_de_l_element(svc):
    infusion = svc.best_for({"feu": 100}, PLANTE)
    assert infusion.name_for("Coup Tranchant") == "Coup Tranchant de Feu"


def test_une_infusion_negligeable_ne_renomme_pas_la_competence(svc):
    """« Coup Tranchant de Terre » pour +0,4 % serait du bruit."""
    infusion = svc.best_for({}, {})
    assert infusion.name_for("Coup Tranchant") == "Coup Tranchant"
