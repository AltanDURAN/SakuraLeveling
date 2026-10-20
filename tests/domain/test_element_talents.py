"""Talents élémentaires : tirage, éléments morts, bonus, essences, papiers."""

import random

import pytest

from app.domain.services.element_affinity_progression_service import (
    ElementAffinityProgressionService,
)
from app.domain.services.element_talent_service import (
    ALL_DEAD_CAP,
    ALL_DEAD_TALENT,
    ElementTalent,
    essence_gain,
    paper_price,
    roll_talents,
)


class _Rng(random.Random):
    """Tirages imposés : d'abord les 8 talents, puis (élément, bonus) par mort."""

    def __init__(self, ints, choices=()):
        super().__init__(0)
        self._ints, self._choices = list(ints), list(choices)

    def randint(self, a, b):
        return self._ints.pop(0)

    def choice(self, seq):
        return self._choices.pop(0) if self._choices else seq[0]


def test_tirage_de_base_sans_element_mort():
    talents = roll_talents(_Rng([1, 2, 3, 4, 5, 6, 7, 8]))
    assert [t.talent for t in talents.values()] == [1, 2, 3, 4, 5, 6, 7, 8]
    assert all(t.cap == 100 and not t.dead for t in talents.values())


def test_chaque_element_mort_booste_un_element_vivant():
    codes = list(roll_talents(random.Random(1)))
    # 2 morts → 2 bonus (+18 puis +25) tombent sur le même élément vivant.
    rng = _Rng([0, 0, 5, 5, 5, 5, 5, 7, 18, 25], choices=[codes[7], codes[7]])
    talents = roll_talents(rng)
    assert talents[codes[0]].dead and talents[codes[1]].dead
    assert talents[codes[7]] == ElementTalent(7 + 18 + 25, boosts=2, cap=300)


def test_huit_elements_morts_recompenses():
    talents = roll_talents(_Rng([0] * 8))
    assert all(t == ElementTalent(ALL_DEAD_TALENT, 0, ALL_DEAD_CAP) for t in talents.values())


def test_un_bonus_ne_tombe_jamais_sur_un_element_mort():
    for seed in range(300):
        talents = roll_talents(random.Random(seed))
        dead = [c for c, t in talents.items() if t.dead]
        assert all(talents[c].boosts == 0 for c in dead)
        assert sum(t.boosts for t in talents.values()) == len(dead) or len(dead) == 8


def test_gain_d_essences_juste_en_moyenne_et_sans_decimale():
    rng = random.Random(3)
    gains = [essence_gain(1, 3, rng) for _ in range(20000)]
    assert set(gains) <= {1, 2}
    assert sum(gains) / len(gains) == pytest.approx(1.3, abs=0.02)
    assert essence_gain(2, 10) == 4          # +100 %
    assert essence_gain(5, 0) == 0           # élément mort


def test_le_plafond_suit_les_bonus():
    service = ElementAffinityProgressionService()
    capped = service.apply_essences(100, 0, 10**6)
    assert capped.new_affinity == 100
    boosted = service.apply_essences(100, 0, 10**6, cap=300)
    assert boosted.new_affinity == 300


def test_prix_des_papiers():
    prices = [0, 2000, 5000]
    assert paper_price(0, prices) == 0       # le premier est gratuit
    assert paper_price(1, prices) == 2000
    assert paper_price(5, prices) == 5000    # au-delà de la liste : dernier prix
    assert paper_price(8, prices) is None    # tout est découvert
