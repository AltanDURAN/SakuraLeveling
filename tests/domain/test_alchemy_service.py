"""Règles pures de l'alchimie d'Elna (26/10/2026)."""

import random
from datetime import UTC, datetime, timedelta

from app.domain.services import alchemy_service as alchemy
from app.domain.services.health_regeneration_service import HealthRegenerationService
from app.domain.services.status_effect_service import StatusEffectService
from app.infrastructure.artisans import artisan_loader

RECIPE = alchemy.Recipe("potion_x", (("gel_e", 4), ("dent_de_gobelin", 2)), fee_per_level=4)


def test_la_confection_suit_le_niveau_et_la_remise():
    assert alchemy.brew_fee(RECIPE, level=50) == 200
    assert alchemy.brew_fee(RECIPE, level=50, quantity=3) == 600
    assert alchemy.brew_fee(RECIPE, level=50, quantity=3, discount_pct=10) == 540


def test_le_lot_maximal_est_borne_par_les_ingredients_et_l_or():
    owned = {"gel_e": 13, "dent_de_gobelin": 10}
    assert alchemy.max_brewable(RECIPE, owned, gold=10_000, level=10) == 3   # 13 gelées / 4
    assert alchemy.max_brewable(RECIPE, owned, gold=85, level=10) == 2      # 40 or la potion
    assert alchemy.max_brewable(RECIPE, {}, gold=10_000, level=10) == 0


def test_potions_offertes_selon_la_maitrise():
    assert alchemy.bonus_potions(100, 0) == 0
    got = alchemy.bonus_potions(1000, 20, random.Random(0))
    assert 150 < got < 250


def test_elixir_de_recuperation_triple_la_regen_sur_sa_fenetre_seulement():
    now = datetime.now(UTC)
    last = now - timedelta(minutes=120)
    window = (now - timedelta(minutes=90), now - timedelta(minutes=30), 3.0)   # 60 min ×3
    # 120 min dont 60 boostées ×3 → 240 minutes de régénération.
    assert alchemy.boosted_seconds(last, now, [window]) == 240 * 60
    hp = HealthRegenerationService().apply_out_of_combat_regeneration(
        current_hp=0, max_hp=10_000, hp_regeneration=5, last_updated_at=last, now=now, boosts=[window])
    assert hp == 1200
    # Une fenêtre déjà comptée (avant la dernière mise à jour) ne compte plus.
    assert alchemy.boosted_seconds(now - timedelta(minutes=10), now, [window]) == 600


def test_effets_differents_additionnes_meme_effet_jamais():
    bonuses = StatusEffectService().aggregate([], {"elixir_attack": 1.10, "elixir_defense": 1.10})
    assert round(bonuses.attack_percent, 6) == 0.10 and round(bonuses.defense_percent, 6) == 0.10
    assert bonuses.max_hp_percent == 0 and bonuses.all_stats_multiplier == 1.0
    # La régénération n'est pas une stat de combat.
    assert StatusEffectService().aggregate([], {"elixir_regen": 3.0}).attack_percent == 0


def test_le_catalogue_d_elna_est_coherent():
    import json
    from pathlib import Path

    items = {i["code"]: i for i in json.loads(
        (Path(__file__).resolve().parents[2] / "app/infrastructure/content/items.json").read_text("utf-8"))}
    elna = artisan_loader.get_alchemist()
    assert elna.name == "Elna" and len(elna.recipes) >= 7
    for recipe in elna.recipes:
        potion = items[recipe.item_code]
        assert potion["category"] == "consumable"
        assert alchemy.effect_text(potion["stat_bonuses"]) != "effet inconnu"
        assert recipe.fee_per_level > 0 and recipe.ingredients
        for code, _ in recipe.ingredients:
            assert items[code]["category"] == "resource"   # un matériau de famille
    kinds = {alchemy.elixir_of(items[r.item_code]["stat_bonuses"]).kind
             for r in elna.recipes if alchemy.elixir_of(items[r.item_code]["stat_bonuses"])}
    assert kinds == {"regen", "attack", "defense", "max_hp"}
