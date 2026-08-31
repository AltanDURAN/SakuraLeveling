"""Éligibilité aux épreuves de rang.

Le rang ouvre les zones de farm : se tromper ici, c'est soit bloquer un joueur
légitime, soit ouvrir une zone à quelqu'un qui n'a rien prouvé.
"""

import pytest

from app.domain.services.rank_trial_service import (
    GuardianStats,
    RankTrial,
    RankTrialService,
)

RANK_ORDER = ["F", "E", "D", "C", "B", "A", "S", "SS", "SSS"]


def _trial(rank: str, power: int) -> RankTrial:
    return RankTrial(
        rank=rank,
        required_power=power,
        guardian=GuardianStats(
            name=f"Gardien {rank}", lore="", max_hp=100, attack=10, defense=5,
        ),
    )


@pytest.fixture
def svc():
    return RankTrialService(
        [
            _trial("E", 1_125), _trial("D", 2_450), _trial("C", 4_300),
            _trial("B", 6_600), _trial("A", 9_500), _trial("S", 12_600),
            _trial("SS", 36_000), _trial("SSS", 292_000),
        ],
        RANK_ORDER,
    )


# ------------------------------------------------------------ progression --
@pytest.mark.parametrize(
    "courant, attendu",
    [("F", "E"), ("E", "D"), ("A", "S"), ("SS", "SSS"), ("SSS", None)],
)
def test_rang_suivant(svc, courant, attendu):
    assert svc.next_rank(courant) == attendu


def test_un_rang_inconnu_repart_du_plus_bas(svc):
    """Rôle retiré à la main : on ne plante pas, on repropose la 1re épreuve."""
    assert svc.next_rank("inconnu") == "F"


def test_l_epreuve_correspond_au_rang_suivant(svc):
    assert svc.trial_for("F").rank == "E"
    assert svc.trial_for("B").rank == "A"


def test_au_sommet_il_n_y_a_plus_d_epreuve(svc):
    assert svc.trial_for("SSS") is None
    elig = svc.evaluate("SSS", power=10**9)
    assert elig.at_max_rank and not elig.can_attempt


# --------------------------------------------------------------- seuil --
def test_puissance_insuffisante_bloque(svc):
    elig = svc.evaluate("F", power=1_000)
    assert not elig.can_attempt
    assert elig.missing_power == 125
    assert "1 000" in elig.blocked_reason or "1000" in elig.blocked_reason


def test_seuil_exact_ouvre_l_epreuve(svc):
    elig = svc.evaluate("F", power=1_125)
    assert elig.can_attempt
    assert elig.blocked_reason is None


def test_puissance_largement_au_dessus_ouvre_aussi(svc):
    assert svc.evaluate("F", power=999_999).can_attempt


def test_le_seuil_est_celui_du_rang_VISE_pas_du_rang_courant(svc):
    """Un joueur rang F très puissant n'obtient PAS D d'un coup : il doit
    passer E d'abord. La progression reste séquentielle."""
    elig = svc.evaluate("F", power=50_000)
    assert elig.trial.rank == "E"


# ------------------------------------------------------------ cooldown --
def test_le_cooldown_bloque_meme_avec_la_puissance(svc):
    elig = svc.evaluate("F", power=99_999, on_cooldown_until="dans 3 h")
    assert not elig.can_attempt
    assert "dans 3 h" in elig.blocked_reason


def test_le_cooldown_n_efface_pas_l_epreuve_visee(svc):
    """On continue d'afficher le gardien : le joueur doit savoir ce qui
    l'attend même pendant l'attente."""
    elig = svc.evaluate("F", power=99_999, on_cooldown_until="dans 3 h")
    assert elig.trial is not None and elig.trial.rank == "E"


# ------------------------------------------------------------- contenu --
def test_le_contenu_livre_couvre_toute_la_chaine():
    """Chaque rang sauf le dernier doit avoir son épreuve, sinon un joueur
    resterait bloqué sans aucun moyen de monter."""
    from app.infrastructure.rank_trials import rank_trial_loader

    trials = {t.rank for t in rank_trial_loader.list_trials()}
    assert trials == set(RANK_ORDER[1:])


def test_les_gardiens_laissent_passer_des_degats():
    """Invariant du projet : la défense d'un adversaire ne doit jamais
    approcher l'attaque du joueur, sinon les coups tombent au plancher de 1."""
    from app.infrastructure.rank_trials import rank_trial_loader

    for trial in rank_trial_loader.list_trials():
        # Le gardien est calibré sur un joueur au seuil ; sa défense doit
        # rester une fraction de l'attaque attendue, jamais l'égaler.
        assert trial.guardian.defense < trial.guardian.attack, trial.rank
        assert trial.guardian.max_hp > 0
