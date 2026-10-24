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


class _FixedRng:
    def __init__(self, value):
        self.value = value

    def random(self):
        return self.value


def test_bonus_de_drop_bride_a_un_et_demi():
    rng = random.Random(3)
    n = 200_000
    hits = sum(roll_drop(rng, drop_bonus=4.0) is not None for _ in range(n))
    boosted = sum(v * (1.5 if k not in ("legendary", "mythic") else 1) for k, v in DROP_RATES_PCT.items())
    assert abs(100 * hits / n - boosted) < 0.35


def test_bonus_de_drop_ne_touche_ni_legendaire_ni_mythique():
    # Les tranches les plus rares (en tête du tirage) gardent leur largeur.
    mythic = DROP_RATES_PCT["mythic"] / 100
    legendary = DROP_RATES_PCT["legendary"] / 100
    just_after = (mythic + legendary) * 1.0001
    assert roll_drop(_FixedRng(mythic * 0.99), drop_bonus=1.5) == "mythic"
    assert roll_drop(_FixedRng(mythic * 1.01), drop_bonus=1.5) == "legendary"
    assert roll_drop(_FixedRng(just_after), drop_bonus=1.5) == "epic"
    # Trouvaille, elle, élargit TOUTES les tranches.
    assert roll_drop(_FixedRng(mythic * 1.05), drop_rate_multiplier=1.10) == "mythic"


def test_un_malus_n_existe_pas():
    assert roll_drop(_FixedRng(0.09), drop_bonus=0.5) == roll_drop(_FixedRng(0.09))
