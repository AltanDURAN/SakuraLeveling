import random

from app.domain.services.gear_service import (
    DROP_RATES_PCT,
    Rarity,
    fusion_cost,
    gear_stats,
    next_rarity,
    passive_active,
    roll_drop,
)

SWORD = {"attack_pct": 8, "crit_chance": 3}


def test_rarete_multiplie_principale_et_secondaire_differemment():
    assert gear_stats(SWORD, "common") == {"attack_pct": 8.0, "crit_chance": 3.0}
    assert gear_stats(SWORD, "legendary") == {"attack_pct": 32.0, "crit_chance": 7.5}
    assert gear_stats(SWORD, "mythic") == {"attack_pct": 44.0, "crit_chance": 9.0}


def test_vitesse_entiere_et_tronquee():
    assert gear_stats({"speed": 1}, "legendary") == {"speed": 2.0}
    assert gear_stats({"speed": -1}, "legendary") == {"speed": -2.0}
    assert gear_stats({"speed": 1}, "uncommon") == {"speed": 1.0}


def test_forge_sacree_un_pour_cent_par_niveau_plafonne():
    assert gear_stats({"attack_pct": 10}, "common", 10)["attack_pct"] == 11.0
    assert gear_stats({"attack_pct": 10}, "common", 99)["attack_pct"] == 11.0


def test_fusion():
    assert next_rarity("common") == Rarity.UNCOMMON
    assert next_rarity("epic") == Rarity.LEGENDARY
    assert next_rarity("legendary") is None
    assert next_rarity("mythic") is None
    assert fusion_cost("epic") == (40_000, 100)
    assert fusion_cost("legendary") is None


def test_passif_a_partir_de_l_epique():
    assert not passive_active("rare")
    assert passive_active("epic") and passive_active("mythic")


def test_tirage_respecte_les_taux():
    rng = random.Random(1)
    n = 400_000
    counts = {}
    for _ in range(n):
        r = roll_drop(rng)
        counts[r] = counts.get(r, 0) + 1
    for rarity in ("common", "uncommon", "rare"):
        assert abs(100 * counts[rarity] / n - DROP_RATES_PCT[rarity]) < 0.15
    total = sum(v for k, v in counts.items() if k is not None)
    assert abs(100 * total / n - sum(DROP_RATES_PCT.values())) < 0.2


def test_multiplicateur_de_drop():
    rng = random.Random(2)
    n = 200_000
    hits = sum(roll_drop(rng, drop_rate_multiplier=2.0) is not None for _ in range(n))
    assert abs(100 * hits / n - 2 * sum(DROP_RATES_PCT.values())) < 0.4
