"""Règles pures de l'offrande commune (`offering_service`)."""

import random

from app.domain.services import offering_service as osvc
from app.infrastructure.offering import deity_loader


def test_formule_de_l_auteur():
    assert osvc.grown(1_500, 1) == round((1_500 + 75) * 1.04)          # 1er remplissage
    assert osvc.grown(10_000, 20) == round((10_000 + 75 * 20) * 1.04)
    assert osvc.decayed(40_000, 1) == 39_200                            # −2 % par jour sans
    assert osvc.decayed(1_600, 30) == osvc.BASE_TARGET                  # jamais sous la base


def test_jamais_deux_fois_la_meme_divinite_de_suite():
    deities = deity_loader.list_deities()
    rng = random.Random(3)
    assert all(osvc.pick_deity(deities, "kairos", rng).code != "kairos" for _ in range(50))


def test_chaque_divinite_porte_un_effet_connu_et_aucune_ne_donne_d_or():
    deities = deity_loader.list_deities()
    assert len(deities) == 7 and {d.effect for d in deities} <= osvc.EFFECTS
    assert not any("gold" in d.effect for d in deities)       # un puits d'or, pas une source
    assert osvc.effect_value(deity_loader.get_deity("sylve"), "regen_mult") == 5
    assert osvc.effect_value(deity_loader.get_deity("kairos"), "xp_pct") == 10
