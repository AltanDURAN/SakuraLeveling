"""Règles pures de l'offrande commune (`offering_service`)."""

import random

from app.domain.services import offering_service as osvc
from app.infrastructure.offering import offering_loader


def test_formule_de_l_auteur():
    assert osvc.grown(1_500, 1) == round((1_500 + 75) * 1.04)          # 1er remplissage
    assert osvc.grown(10_000, 20) == round((10_000 + 75 * 20) * 1.04)
    assert osvc.decayed(40_000, 1) == 39_200                            # −2 % par jour sans
    assert osvc.decayed(1_600, 30) == osvc.BASE_TARGET                  # jamais sous la base


def test_jamais_deux_fois_la_meme_divinite_de_suite():
    deities = offering_loader.list_deities()
    rng = random.Random(3)
    assert all(osvc.pick_deity(deities, "kairos", rng).code != "kairos" for _ in range(50))


def test_chaque_divinite_porte_un_effet_connu_et_aucune_ne_donne_d_or():
    deities = offering_loader.list_deities()
    assert len(deities) == 7 and {d.effect for d in deities} <= osvc.EFFECTS
    assert not any("gold" in d.effect for d in deities)       # un puits d'or, pas une source
    assert osvc.effect_value(offering_loader.get_deity("sylve"), "regen_mult") == 5
    assert osvc.effect_value(offering_loader.get_deity("kairos"), "xp_pct") == 10


def test_parametres_reglables_et_simulation():
    params = osvc.OfferingParams(base_target=1_000, step_per_fill=0, growth_pct=10, decay_pct=5, blessing_hours=12)
    assert osvc.grown(1_000, 1, params) == 1_100 and osvc.decayed(2_000, 1, params) == 1_900
    assert osvc.simulate_daily(params, 3) == [(1, 1_000, 1_000), (2, 1_100, 2_100), (3, 1_210, 3_310)]
    assert osvc.validate_params(params) == []
    assert len(osvc.validate_params(osvc.OfferingParams(base_target=0, decay_pct=100, blessing_hours=0))) == 3


def test_les_parametres_du_contenu_sont_ceux_de_l_auteur():
    assert offering_loader.get_params() == osvc.DEFAULT_PARAMS
