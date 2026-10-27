"""Règles pures de l'offrande commune (`offering_service`)."""

import random

from app.domain.services import offering_service as osvc
from app.infrastructure.offering import deity_loader


def test_le_prix_monte_a_chaque_remplissage_et_redescend_sans():
    assert osvc.grown(25_000) == 27_000
    assert osvc.decayed(40_000, 1) == 38_000
    assert osvc.decayed(26_000, 30) == osvc.BASE_TARGET      # jamais sous la base


def test_jamais_deux_fois_la_meme_divinite_de_suite():
    deities = deity_loader.list_deities()
    rng = random.Random(3)
    assert all(osvc.pick_deity(deities, "aurelia", rng).code != "aurelia" for _ in range(50))


def test_chaque_divinite_porte_un_effet_connu():
    deities = deity_loader.list_deities()
    assert len(deities) >= 5 and {d.effect for d in deities} <= osvc.EFFECTS
    sylve = deity_loader.get_deity("sylve")
    assert osvc.effect_value(sylve, "regen_mult") == 2 and osvc.effect_value(sylve, "gold_pct") == 0
