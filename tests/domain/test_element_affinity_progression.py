"""Progression d'affinité par essences : coût N→N+1 = N+1, auto-conversion."""

from app.domain.services.element_affinity_progression_service import (
    ElementAffinityProgressionService,
    MAX_AFFINITY,
)
from app.shared.enums import parse_elements


def _svc():
    return ElementAffinityProgressionService()


def test_cost_for_next_level():
    svc = _svc()
    assert svc.cost_for_next_level(0) == 1
    assert svc.cost_for_next_level(1) == 2
    assert svc.cost_for_next_level(99) == 100
    assert svc.cost_for_next_level(100) is None  # max → plus de palier


def test_one_essence_levels_0_to_1():
    conv = _svc().apply_essences(current_affinity=0, current_essences=0, added_essences=1)
    assert conv.new_affinity == 1
    assert conv.remaining_essences == 0
    assert conv.levels_gained == 1


def test_not_enough_essence_accumulates():
    # Affinité 5 → 6 coûte 6 essences. Avec 3, rien ne monte, ça s'accumule.
    conv = _svc().apply_essences(current_affinity=5, current_essences=3, added_essences=2)
    assert conv.new_affinity == 5
    assert conv.remaining_essences == 5
    assert conv.levels_gained == 0


def test_multiple_levels_in_one_batch():
    # Depuis 0 avec 6 essences : 0→1 (1), 1→2 (2), 2→3 (3) = 6 consommées, reste 0.
    conv = _svc().apply_essences(current_affinity=0, current_essences=0, added_essences=6)
    assert conv.new_affinity == 3
    assert conv.remaining_essences == 0
    assert conv.levels_gained == 3


def test_leftover_carries():
    # 7 essences depuis 0 : 1+2+3 = 6 consommées pour atteindre 3, reste 1.
    conv = _svc().apply_essences(0, 0, 7)
    assert conv.new_affinity == 3
    assert conv.remaining_essences == 1


def test_capped_at_max():
    conv = _svc().apply_essences(current_affinity=MAX_AFFINITY, current_essences=0, added_essences=50)
    assert conv.new_affinity == MAX_AFFINITY
    assert conv.levels_gained == 0
    # Au max, les essences s'accumulent sans effet.
    assert conv.remaining_essences == 50


def test_parse_elements():
    assert parse_elements("") == []
    assert parse_elements(None) == []
    assert parse_elements("feu") == ["feu"]
    assert parse_elements("feu,glace") == ["feu", "glace"]
    assert parse_elements("feu glace") == ["feu", "glace"]
    assert parse_elements("feu,feu") == ["feu"]  # dédup
    assert parse_elements("feu,inconnu,eau") == ["feu", "eau"]  # filtre invalides
