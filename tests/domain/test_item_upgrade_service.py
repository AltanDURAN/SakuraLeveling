"""Règles pures de l'amélioration d'équipement (+0 → +10, +10 %/niveau)."""

from app.domain.services.item_upgrade_service import (
    MAX_ITEM_LEVEL,
    copies_required,
    fusion_gold_cost,
    level_multiplier,
    scaled_bonuses,
)


def test_plus_dix_vaut_le_double_jamais_plus():
    assert level_multiplier(0) == 1.0
    assert level_multiplier(MAX_ITEM_LEVEL) == 2.0
    assert level_multiplier(99) == 2.0
    assert level_multiplier(-3) == 1.0


def test_les_bonus_affiches_suivent_le_niveau_y_compris_les_malus():
    assert scaled_bonuses({"attack_pct": 20, "speed": -2}, 5) == {"attack_pct": 30, "speed": -3}


def test_les_valeurs_non_numeriques_ne_sont_pas_touchees():
    assert scaled_bonuses({"effect": "heal_percent", "value": 10}, 10) == {
        "effect": "heal_percent", "value": 20,
    }


def test_il_faut_toujours_garder_une_copie_par_emplacement_porte():
    assert copies_required(0) == 2
    assert copies_required(1) == 2
    assert copies_required(2) == 3


def test_le_prix_est_proportionnel_au_niveau_vise():
    assert fusion_gold_cost(1000, 0, 50) == 500
    assert fusion_gold_cost(1000, 9, 50) == 5000
