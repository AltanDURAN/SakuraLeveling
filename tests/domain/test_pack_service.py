"""Meutes de zone (`pack_service`) : récompenses, butin, compagnons."""

import random
from types import SimpleNamespace

from app.domain.services import pack_service as ps


def test_recompense_d_une_meute():
    assert ps.pack_reward([50]) == 50                                  # un monstre seul : inchangé
    assert ps.pack_reward([100, 100]) == round(200 * 0.87 * 1.25)
    assert ps.pack_reward([10, 20, 30]) == round(60 * 0.73 * 1.25)


def test_le_butin_d_un_monstre_de_meute_tombe_avec_le_facteur():
    rng = random.Random(1)
    assert all(ps.loot_roll(1, rng) for _ in range(50))
    rate = sum(ps.loot_roll(3, rng) for _ in range(4000)) / 4000
    assert abs(rate - 0.73) < 0.03


def test_compagnons_de_puissance_voisine():
    mob = lambda code, power: SimpleNamespace(code=code, power=power, spawn_weight=1)
    leader = mob("chef", 100)
    pool = [mob("faible", 30), mob("voisin", 120), mob("fort", 400)]
    picked = ps.pick_companions(leader, pool, lambda m: m.power, 3, random.Random(0))
    assert len(picked) == 2 and {m.code for m in picked} == {"voisin"}
    assert ps.pick_companions(leader, [mob("fort", 400)], lambda m: m.power, 2) == []
