"""Règles des artisans : maîtrise, prix, délai, plafond de puissance."""

import pytest

from app.domain.entities.artisan import (
    ArtisanDefinition,
    MasteryTier,
    PricingRules,
)
from app.domain.services.artisan_service import ArtisanService


def _tier(level, orders, ceiling, discount=0, duration=100):
    return MasteryTier(
        level=level,
        code=f"t{level}",
        name=f"Palier {level}",
        orders_required=orders,
        max_item_power=ceiling,
        gold_discount_pct=discount,
        duration_pct=duration,
    )


def _artisan(tiers=None):
    return ArtisanDefinition(
        code="forgeron", name="Borak", title="Forgeron", verb="forger",
        work_noun="forge", image="", categories=("arme",),
        greeting="", accent=(0, 0, 0),
        tiers=tuple(tiers or [
            _tier(1, 0, 40),
            _tier(2, 10, 120, discount=5, duration=90),
            _tier(3, 30, 350, discount=10, duration=80),
            _tier(4, 75, 0, discount=15, duration=65),
        ]),
    )


@pytest.fixture
def svc():
    return ArtisanService(PricingRules())


# ------------------------------------------------------------- maîtrise --
@pytest.mark.parametrize(
    "orders, attendu",
    [(0, 1), (9, 1), (10, 2), (29, 2), (30, 3), (74, 3), (75, 4), (500, 4)],
)
def test_palier_selon_les_commandes_terminees(svc, orders, attendu):
    assert svc.tier_for(_artisan(), orders).level == attendu


def test_commandes_restantes_avant_le_palier_suivant(svc):
    a = _artisan()
    assert svc.orders_until_next_tier(a, 0) == 10
    assert svc.orders_until_next_tier(a, 7) == 3
    # au maximum, plus rien à attendre
    assert svc.orders_until_next_tier(a, 75) == 0


def test_progression_vers_le_palier_suivant(svc):
    a = _artisan()
    assert svc.tier_progress(a, 0) == pytest.approx(0.0)
    assert svc.tier_progress(a, 5) == pytest.approx(0.5)
    assert svc.tier_progress(a, 75) == pytest.approx(1.0)  # palier max


def test_palier_maximum_n_a_pas_de_suivant(svc):
    assert svc.next_tier(_artisan(), 75) is None


# ------------------------------------------------------- plafond de puissance --
def test_un_palier_refuse_les_pieces_trop_puissantes(svc):
    a = _artisan()
    devis = svc.quote(a, power=200, orders_completed=0)
    assert not devis.accepted
    assert devis.required_tier.level == 3  # 200 ≤ 350


def test_le_dernier_palier_accepte_tout(svc):
    a = _artisan()
    devis = svc.quote(a, power=999_999, orders_completed=75)
    assert devis.accepted


def test_piece_dans_le_plafond_est_acceptee(svc):
    devis = svc.quote(_artisan(), power=40, orders_completed=0)
    assert devis.accepted and devis.required_tier is None


# ------------------------------------------------------------------ prix --
def test_le_prix_croit_avec_la_puissance(svc):
    a = _artisan()
    prix = [svc.quote(a, p, 75).gold_cost for p in (0, 50, 100, 200)]
    assert prix == sorted(prix)
    assert len(set(prix)) == len(prix)


def test_le_prix_croit_plus_vite_que_la_puissance(svc):
    """Doubler la puissance doit coûter PLUS du double (hors part fixe)."""
    a = _artisan()
    base = svc.pricing.gold_base
    p100 = svc.quote(a, 100, 75).gold_cost - base
    p200 = svc.quote(a, 200, 75).gold_cost - base
    assert p200 > 2 * p100


def test_la_maitrise_reduit_le_prix(svc):
    a = _artisan()
    apprenti = svc.quote(a, 30, 0).gold_cost
    legendaire = svc.quote(a, 30, 75).gold_cost
    assert legendaire < apprenti


def test_le_prix_reste_positif(svc):
    assert svc.quote(_artisan(), 0, 75).gold_cost >= 1


# ----------------------------------------------------------------- délai --
def test_le_delai_croit_avec_la_puissance(svc):
    a = _artisan()
    assert svc.quote(a, 200, 75).duration_seconds > svc.quote(a, 10, 75).duration_seconds


def test_la_maitrise_reduit_le_delai(svc):
    a = _artisan()
    assert (
        svc.quote(a, 30, 75).duration_seconds
        < svc.quote(a, 30, 0).duration_seconds
    )


def test_le_delai_est_plafonne(svc):
    a = _artisan()
    devis = svc.quote(a, 10_000_000, 0)
    assert devis.duration_seconds <= svc.pricing.duration_max_s


def test_duration_pct_a_zero_rend_le_travail_instantane(svc):
    """Le levier qui permet de désactiver l'attente sans toucher au code."""
    a = _artisan([_tier(1, 0, 0, duration=0)])
    devis = svc.quote(a, 500, 0)
    assert devis.duration_seconds == 0
    assert devis.instant


# ------------------------------------------------------------ annulation --
def test_l_annulation_rembourse_la_part_prevue(svc):
    assert svc.refund_for(200) == 100  # 50 % par défaut
    assert svc.refund_for(0) == 0
