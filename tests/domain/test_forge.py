"""Forge sacrée (équipement v2) : +1 % des stats de la pièce par niveau, 0 → 10.

Le niveau appartient à la COPIE portée (et survit à la fusion : on garde le
plus haut des deux). Une pièce +50 % d'ATK à +10 vaut +55 %.
"""

import pytest

from app.domain.services.stats_service import StatsService
from tests.domain.test_stats_service import build_item, build_profile


def _attack_at_forge_level(level: int) -> int:
    profile = build_profile(points_attack=40)
    item = build_item({"attack_pct": 50}, forge_level=level)
    return StatsService().calculate_player_stats(profile=profile, equipped_items=[item]).attack


def _bare_attack() -> int:
    return StatsService().calculate_player_stats(
        profile=build_profile(points_attack=40), equipped_items=[],
    ).attack


@pytest.mark.parametrize(
    "level, multiplier", [(0, 1.50), (1, 1.505), (10, 1.55), (25, 1.55)],
)
def test_chaque_niveau_ajoute_un_pour_cent_de_la_piece(level, multiplier):
    """+10 au maximum : un niveau hors bornes (donnée corrompue) est plafonné."""
    assert _attack_at_forge_level(level) == round(_bare_attack() * multiplier)


def test_forger_n_affaiblit_jamais_la_piece():
    valeurs = [_attack_at_forge_level(n) for n in range(0, 11)]
    assert valeurs == sorted(valeurs)
    assert valeurs[-1] > valeurs[0]
