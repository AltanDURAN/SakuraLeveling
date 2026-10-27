"""Tests du loader de BossDefinitions (cache module-level)."""

import random

from app.infrastructure.world_boss.boss_definition_loader import (
    clear_cache,
    get_definition,
    list_definitions,
    pick_random_definition,
)


def test_loader_returns_5_bosses():
    clear_cache()
    defs = list_definitions()
    assert len(defs) >= 5  # 5 dans le seed initial, peut grandir


def test_loader_cache_singleton():
    clear_cache()
    a = list_definitions()
    b = list_definitions()
    assert a is b  # même objet retourné (cache)


def test_get_definition_by_code():
    clear_cache()
    boss = get_definition("slime_titan")
    assert boss is not None
    assert boss.name == "Titan Visqueux"
    assert boss.tier == "intro"


def test_get_definition_unknown_returns_none():
    clear_cache()
    assert get_definition("dragon_inexistant") is None


def test_pick_random_definition_respects_weights():
    """Avec une seed déterministe et des poids très inégaux, on doit majoritairement
    obtenir le boss avec le poids le plus élevé."""
    clear_cache()
    rng = random.Random(0)
    counts = {}
    for _ in range(200):
        d = pick_random_definition(rng=rng)
        counts[d.code] = counts.get(d.code, 0) + 1

    # slime_titan a poids 100 (le plus haut) ; ancient_dragon a 5
    # → sur 200 tirages, slime_titan doit dominer largement vs dragon
    assert counts.get("slime_titan", 0) > counts.get("ancient_dragon", 0) * 5


def test_modifiers_loaded_correctly():
    clear_cache()
    titan = get_definition("slime_titan")
    # La VALEUR vient du recalibrage (scripts/restat_bosses.py) : on vérifie le
    # chargement, pas l'équilibrage.
    assert titan.modifiers.get("damage_immunity_threshold", 0) > 0
    assert titan.modifiers.get("auto_heal_per_turn", 0) > 0

    warlord = get_definition("gobelin_warlord")
    assert "adds" in warlord.modifiers

    dragon = get_definition("ancient_dragon")
    assert "damage_immunity_threshold" in dragon.modifiers
    # Phases, ultime et gardes (27/10/2026) : des champs à part, plus des modifiers.
    assert "phases" not in dragon.modifiers and "enrage_below_pct" not in dragon.modifiers


def test_phases_ultime_et_gardes_charges():
    clear_cache()
    for code in ("slime_titan", "gobelin_warlord", "stone_colossus", "shadow_wraith", "ancient_dragon"):
        boss = get_definition(code)
        assert [ph["below_pct"] for ph in boss.phases] == [75, 50, 25]
        assert all(ph.get("name") for ph in boss.phases)
        assert boss.ultimate.get("name") and boss.ultimate.get("every", 0) >= 2
        assert len(boss.guards) == 2 and all(g["max_hp"] > 0 and g["attack"] > 0 for g in boss.guards)


def test_each_boss_has_an_element():
    clear_cache()
    expected = {
        "slime_titan": "eau",
        "gobelin_warlord": "feu",
        "stone_colossus": "terre",
        "shadow_wraith": "tenebre",
        "ancient_dragon": "lumiere",
    }
    for code, elem in expected.items():
        assert get_definition(code).element == elem
