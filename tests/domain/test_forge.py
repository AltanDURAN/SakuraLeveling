"""Forge sacrée : chaque niveau rajoute une fois les bonus de base de la pièce.

En saison 1 les bonus d'équipement sont des POURCENTAGES du socle, donc forger
amplifie le pourcentage — pas une valeur plate. Une pièce +10 % forgée niveau 2
vaut +30 %.
"""

import pytest

from app.domain.services.forge_service import ForgeService
from app.domain.services.stats_service import StatsService
from tests.domain.test_stats_service import build_item, build_profile


def _attack_at_forge_level(level: int) -> int:
    profile = build_profile(points_attack=20)
    item = build_item({"attack_pct": 10})
    return StatsService().calculate_player_stats(
        profile=profile,
        equipped_items=[item],
        item_levels={item.item_definition.id: level} if level else None,
    ).attack


def _bare_attack() -> int:
    return StatsService().calculate_player_stats(
        profile=build_profile(points_attack=20), equipped_items=[],
    ).attack


@pytest.mark.parametrize("level, multiplier", [(0, 1.10), (1, 1.20), (3, 1.40)])
def test_chaque_niveau_de_forge_rajoute_le_bonus_de_base(level, multiplier):
    assert _attack_at_forge_level(level) == round(_bare_attack() * multiplier)


def test_forger_augmente_toujours_la_piece():
    valeurs = [_attack_at_forge_level(n) for n in range(0, 5)]
    assert valeurs == sorted(valeurs)
    assert len(set(valeurs)) == len(valeurs)


def test_le_service_de_forge_sait_dire_quand_une_piece_est_au_max():
    service = ForgeService()
    assert service.is_maxed(10, 10) is True
    assert service.is_maxed(3, 10) is False


def test_le_gain_par_niveau_porte_bien_sur_les_pourcentages():
    """Une pièce en % doit annoncer son gain en %, pas en valeur plate."""
    gains = ForgeService().gain_per_level({"attack_pct": 10, "crit_chance": 2})
    assert gains.get("attack_pct") == 10
    assert gains.get("crit_chance") == 2
