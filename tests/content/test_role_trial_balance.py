"""Épreuves de rôle : chaque spécialiste gagne SON épreuve, dans chaque
variante, à plusieurs niveaux (builds de `scripts/reference_roles.py`).

Pièges trouvés au calibrage (25/10/2026) : sans ces règles, le Soigneur
gagnait l'épreuve TANK en se soignant lui-même, et ne marquait presque rien en
SOUTIEN quand le Bourreau frappait tout le monde."""

import importlib.util
import sys
from pathlib import Path

import pytest

from app.domain.services.role_trial_service import VARIANTS, run_trial

_ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("reference_roles", _ROOT / "scripts/reference_roles.py")
ROLES = importlib.util.module_from_spec(_spec)
sys.modules["reference_roles"] = ROLES
_spec.loader.exec_module(ROLES)

SPECIALIST = {"dps": "dps", "tank": "tank", "soutien": "support"}


def _score(trial_role: str, build_role: str, level: int, variant) -> int:
    b = ROLES.build(build_role, level)
    return run_trial(trial_role, variant, player_id=1, name="p", stats=b.stats,
                     passives=b.passives, tactic=b.tactic, seed=0).score


@pytest.mark.parametrize("level", (30, 60, 100))
@pytest.mark.parametrize("variant", [v for vs in VARIANTS.values() for v in vs],
                         ids=lambda v: f"{v.role}-{v.code}")
def test_le_specialiste_gagne_son_epreuve(variant, level):
    scores = {r: _score(variant.role, r, level, variant) for r in ("dps", "tank", "support")}
    best = max(scores, key=scores.get)
    assert best == SPECIALIST[variant.role], scores
    assert scores[best] > 0


def test_un_essai_est_deterministe():
    variant = VARIANTS["dps"][0]
    assert _score("dps", "dps", 60, variant) == _score("dps", "dps", 60, variant)
