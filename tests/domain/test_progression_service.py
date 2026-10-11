"""Courbe de progression — SAISON 1.

Ces tests ne figent PAS des nombres d'équilibrage (ils changeront au prochain
calibrage) mais les PROPRIÉTÉS qui justifient la refonte : la progression doit
ralentir avec le niveau, pour qu'un nouveau joueur rattrape un ancien en
niveaux tout en reconnaissant le temps que l'ancien a investi.
"""

import pytest

from app.domain.services.progression_service import (
    KILLS_FLOOR,
    LEVEL_CAP,
    ProgressionService,
)


@pytest.fixture
def svc():
    return ProgressionService()


# --------------------------------------------------------------- courbe --
def test_le_cout_d_un_niveau_augmente_avec_le_niveau(svc):
    couts = [svc.xp_required_for_next_level(n) for n in (1, 10, 25, 50, 90)]
    assert couts == sorted(couts)
    assert len(set(couts)) == len(couts)


def test_le_nombre_de_kills_par_niveau_augmente(svc):
    """LE point de la refonte : avant, c'était 16 kills constant à vie."""
    assert svc.kills_for_level(99) > 4 * svc.kills_for_level(1)


def test_les_premiers_niveaux_ne_sont_pas_gratuits(svc):
    """Le joueur doit sentir la galère du début — pas de niveau 1→10 instantané."""
    assert svc.kills_for_level(1) >= KILLS_FLOOR
    kills_jusqu_a_10 = sum(svc.kills_for_level(n) for n in range(1, 10))
    assert kills_jusqu_a_10 >= 70


def test_un_nouveau_joueur_progresse_bien_plus_vite_qu_un_ancien(svc):
    """La propriété de rattrapage : à effort égal, le petit niveau gagne
    plusieurs niveaux pendant que le haut niveau en gagne un."""
    effort = svc.kills_for_level(99)          # ce que coûte UN niveau au vétéran
    niveaux_du_nouveau = 0
    restant, niveau = effort, 10
    while restant >= svc.kills_for_level(niveau):
        restant -= svc.kills_for_level(niveau)
        niveau += 1
        niveaux_du_nouveau += 1
    assert niveaux_du_nouveau >= 4


def test_le_budget_total_tient_dans_une_saison(svc):
    """~3 500 kills pour atteindre le cap : entre 6 mois (assidu) et 1 an."""
    total = sum(svc.kills_for_level(n) for n in range(1, LEVEL_CAP))
    assert 2_500 <= total <= 4_500, total


# ------------------------------------------------------------ montée --
def test_sans_assez_d_xp_rien_ne_bouge(svc):
    r = svc.apply_level_up(1, 0, 10, 0)
    assert (r.level, r.xp, r.levels_gained) == (1, 10, 0)
    assert not r.leveled_up


def test_une_montee_donne_un_point_de_stats_ET_un_point_de_competence(svc):
    besoin = svc.xp_required_for_next_level(1)
    r = svc.apply_level_up(1, 0, besoin, 0, 0)
    assert r.level == 2
    assert r.skill_points == 1
    assert r.stat_points == 1
    assert r.leveled_up


def test_plusieurs_niveaux_d_un_coup(svc):
    besoin = sum(svc.xp_required_for_next_level(n) for n in (1, 2, 3))
    r = svc.apply_level_up(1, 0, besoin, 0, 0)
    assert r.level == 4
    assert r.levels_gained == 3
    assert r.stat_points == 3


def test_les_points_deja_possedes_sont_conserves(svc):
    r = svc.apply_level_up(1, 0, svc.xp_required_for_next_level(1), 5, 7)
    assert r.skill_points == 6 and r.stat_points == 8


def test_l_xp_restante_est_reportee(svc):
    besoin = svc.xp_required_for_next_level(1)
    r = svc.apply_level_up(1, 0, besoin + 13, 0)
    assert r.level == 2 and r.xp == 13


# ------------------------------------------------------------- plafond --
def test_le_cap_arrete_la_progression(svc):
    r = svc.apply_level_up(LEVEL_CAP, 0, 10_000_000, 0, 0)
    assert r.level == LEVEL_CAP
    assert r.levels_gained == 0


def test_au_cap_l_xp_n_est_pas_accumulee(svc):
    """Une barre qui se remplit sans jamais rien donner est plus frustrante
    qu'un palier assumé."""
    assert svc.apply_level_up(LEVEL_CAP, 0, 999_999, 0).xp == 0
    assert svc.xp_required_for_next_level(LEVEL_CAP) == 0


def test_une_montee_massive_s_arrete_au_cap(svc):
    r = svc.apply_level_up(1, 0, 10**9, 0, 0)
    assert r.level == LEVEL_CAP
    assert r.stat_points == LEVEL_CAP - 1
