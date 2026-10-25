"""Rangs affichés (F- → Ω) : un joueur TYPIQUE (médiane des quatre profils de
`scripts/reference_roles.py`) affiche le sous-rang de sa tranche de 5 niveaux,
et S au niveau 100. Avant (25/10/2026), les bornes suivaient le joueur de
référence sans classes : un joueur investi affichait S+ dès le niveau 70."""

import importlib.util
import sys
from pathlib import Path

import pytest

from app.domain.services.power_score_service import PowerScoreService, _RANK_THRESHOLDS

_ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("reference_roles", _ROOT / "scripts/reference_roles.py")
ROLES = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("reference_roles", ROLES)
_spec.loader.exec_module(ROLES)

LABELS = [label for _, label in _RANK_THRESHOLDS]


@pytest.mark.parametrize("level", (3, 12, 27, 48, 63, 77, 92, 100))
def test_un_joueur_typique_affiche_le_rang_de_sa_tranche(level):
    rank = PowerScoreService().compute_rank(ROLES.typical_power(level))
    assert rank == LABELS[(level - 1) // 5], f"niveau {level} : {rank}"


def test_niveau_100_typique_rang_s():
    assert PowerScoreService().compute_rank(ROLES.typical_power(100)) == "S"
