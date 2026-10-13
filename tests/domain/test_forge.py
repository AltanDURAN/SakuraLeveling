"""Amélioration d'une pièce (forge sacrée ou fusion) : +10 % de ses bonus par niveau.

En saison 1 les bonus d'équipement sont des POURCENTAGES du socle, donc
améliorer amplifie le pourcentage — pas une valeur plate. Une pièce +50 % à
+2 vaut +60 % ; à +10, +100 % (le double, jamais plus).
"""

import pytest

from app.domain.services.forge_service import ForgeService
from app.domain.services.stats_service import StatsService
from tests.domain.test_stats_service import build_item, build_profile


def _attack_at_forge_level(level: int) -> int:
    profile = build_profile(points_attack=40)
    item = build_item({"attack_pct": 50})
    return StatsService().calculate_player_stats(
        profile=profile,
        equipped_items=[item],
        item_levels={item.item_definition.id: level} if level else None,
    ).attack


def _bare_attack() -> int:
    return StatsService().calculate_player_stats(
        profile=build_profile(points_attack=40), equipped_items=[],
    ).attack


@pytest.mark.parametrize(
    "level, multiplier", [(0, 1.50), (1, 1.55), (3, 1.65), (10, 2.00), (25, 2.00)],
)
def test_chaque_niveau_ajoute_dix_pourcent_de_la_piece(level, multiplier):
    """+10 au maximum : un niveau hors bornes (donnée corrompue) est plafonné."""
    assert _attack_at_forge_level(level) == round(_bare_attack() * multiplier)


def test_forger_augmente_toujours_la_piece():
    valeurs = [_attack_at_forge_level(n) for n in range(0, 11)]
    assert valeurs == sorted(valeurs)
    assert len(set(valeurs)) == len(valeurs)


def test_le_service_de_forge_sait_dire_quand_une_piece_est_au_max():
    service = ForgeService()
    assert service.is_maxed(10, 10) is True
    assert service.is_maxed(3, 10) is False


def test_le_gain_par_niveau_porte_bien_sur_les_pourcentages():
    """Une pièce en % annonce son gain en %, et un niveau vaut 10 % de la pièce."""
    gains = ForgeService().gain_per_level({"attack_pct": 10, "crit_chance": 2})
    assert gains.get("attack_pct") == 1
    assert gains.get("crit_chance") == 0.2
