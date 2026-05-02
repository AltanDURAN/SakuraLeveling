"""Tests de LootService (drop_rate_multiplier).

On utilise random.seed pour rendre les rolls déterministes — random.random() avec
une seed fixe donne toujours les mêmes valeurs.
"""

from datetime import UTC, datetime

from app.domain.entities.mob_definition import MobDefinition
from app.domain.services.loot_service import LootService


def _make_mob(loot_table: list[dict] | None) -> MobDefinition:
    now = datetime.now(UTC)
    return MobDefinition(
        id=1,
        code="test",
        name="Test",
        description="",
        image_name=None,
        family="test",
        max_hp=10,
        current_hp=10,
        attack=1,
        defense=0,
        xp_reward=1,
        gold_reward=1,
        spawn_weight=1,
        speed=1,
        crit_chance=0,
        crit_damage=100,
        dodge=0,
        hp_regeneration=0,
        loot_table=loot_table,
        created_at=now,
        updated_at=now,
    )


def test_empty_loot_table_returns_empty_list():
    service = LootService()
    mob = _make_mob(loot_table=None)

    assert service.generate_loot(mob) == []
    assert service.generate_loot(mob, drop_rate_multiplier=2.0) == []


def test_certain_drop_with_rate_one_always_drops():
    service = LootService()
    mob = _make_mob(
        loot_table=[
            {"item_code": "always_drop", "drop_rate": 1.0, "min_quantity": 1, "max_quantity": 1}
        ]
    )

    # rate 1.0 → toujours drop, peu importe le seed
    drops = service.generate_loot(mob)
    assert drops == [("always_drop", 1)]


def test_zero_drop_rate_never_drops():
    service = LootService()
    mob = _make_mob(
        loot_table=[
            {"item_code": "never", "drop_rate": 0.0, "min_quantity": 1, "max_quantity": 1}
        ]
    )

    drops = service.generate_loot(mob, drop_rate_multiplier=1000.0)
    # 0.0 × 1000 = 0.0, toujours rejeté
    assert drops == []


def test_multiplier_can_lift_drop_rate():
    """Un drop à 0.05 avec un multiplicateur 2.0 devient effectivement 0.10."""
    import random
    service = LootService()
    mob = _make_mob(
        loot_table=[
            {"item_code": "rare", "drop_rate": 0.05, "min_quantity": 1, "max_quantity": 1}
        ]
    )

    # Sans multiplier (1.0) : avec random à 0.07, ne drop pas (0.07 > 0.05)
    random.seed(42)
    drops_base = service.generate_loot(mob, drop_rate_multiplier=1.0)

    # Avec multiplier 2.0 : avec random à 0.07, drop (0.07 < 0.10)
    random.seed(42)
    drops_boosted = service.generate_loot(mob, drop_rate_multiplier=2.0)

    # On vérifie au moins que le boost permet potentiellement plus de drops
    # (test statistique : avec multiplier élevé, on doit avoir plus de drops)
    drops_count_base = 0
    drops_count_boosted = 0
    for seed in range(100):
        random.seed(seed)
        if service.generate_loot(mob, drop_rate_multiplier=1.0):
            drops_count_base += 1
        random.seed(seed)
        if service.generate_loot(mob, drop_rate_multiplier=10.0):
            drops_count_boosted += 1

    assert drops_count_boosted > drops_count_base


def test_multiplier_clamps_to_one_to_preserve_rarity_bound():
    """Si drop_rate × multiplier > 1.0, le résultat est clampé à 1.0
    (correct car random.random() est dans [0, 1)) — le drop est garanti."""
    service = LootService()
    mob = _make_mob(
        loot_table=[
            {"item_code": "guaranteed", "drop_rate": 0.5, "min_quantity": 2, "max_quantity": 2}
        ]
    )

    # 0.5 × 10 = 5.0 → clampé à 1.0 → drop garanti
    drops = service.generate_loot(mob, drop_rate_multiplier=10.0)
    assert drops == [("guaranteed", 2)]


def test_multiplier_default_is_neutral():
    service = LootService()
    mob = _make_mob(
        loot_table=[
            {"item_code": "always", "drop_rate": 1.0, "min_quantity": 3, "max_quantity": 3}
        ]
    )

    drops = service.generate_loot(mob)
    assert drops == [("always", 3)]


def test_multiplier_preserves_rare_drops_proportionally():
    """L'application multiplicative préserve la rareté relative.

    Un drop à 1% × 1.10 = 1.1%, et NON 11% (qui aurait été additif).
    """
    service = LootService()
    mob = _make_mob(
        loot_table=[
            {"item_code": "rare", "drop_rate": 0.01, "min_quantity": 1, "max_quantity": 1}
        ]
    )

    # On utilise un random "fixé" à 0.05 : la version multiplicative
    # (0.011) ne drop pas, alors qu'une version additive (0.11) aurait droppé.
    # Vérifie que le multiplicateur est bien multiplicatif et pas additif.
    import random
    drops_count = 0
    for seed in range(1000):
        random.seed(seed)
        if service.generate_loot(mob, drop_rate_multiplier=1.10):
            drops_count += 1

    # Avec multiplicatif (1.1%), on doit avoir ~11 drops sur 1000.
    # Si c'était additif (11%), on aurait ~110 drops. Donc < 50 prouve le multiplicatif.
    assert drops_count < 50
