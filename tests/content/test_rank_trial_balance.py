"""Épreuves de rang (26/10/2026) : les trois épreuves des défis face au
gardien, au niveau du rang. Chaque profil qui vient de franchir le seuil de
puissance doit pouvoir passer — avant, l'épreuve était une course aux dégâts
et un pur soutien restait bloqué au rang D, un pur tank au rang B."""

import importlib.util
import sys
from pathlib import Path

import pytest

from app.infrastructure.rank_trials import rank_trial_loader

_ROOT = Path(__file__).resolve().parents[2]


def _load(name: str):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, _ROOT / f"scripts/{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


ROLES = _load("reference_roles")
CAL = _load("calibrate_rank_trials")
SPECIALIST_ROLE = {"dps": "dps", "tank": "tank", "support": "soutien"}


def _rates(build_role: str, trial) -> dict[str, float]:
    level = trial.level if build_role == "general" else CAL.gate_level(build_role, trial.required_power, trial.level)
    build = ROLES.build(build_role, level)
    return {role: CAL.pass_rate(CAL.trial_scores(build, role, trial.level, 20), trial.thresholds[role])
            for role in trial.roles()}


@pytest.mark.parametrize("trial", rank_trial_loader.list_trials(), ids=lambda t: t.rank)
def test_chaque_profil_au_seuil_peut_etre_promu(trial):
    for build_role in ("dps", "tank", "support", "general"):
        rates = _rates(build_role, trial)
        assert max(rates.values()) >= 0.5, (build_role, rates)
        # Un spécialiste réussit SON rôle (le soutien soigne à partir du rang C ;
        # avant, il passe par l'épreuve tank).
        own = SPECIALIST_ROLE.get(build_role)
        if own in ("dps", "tank") or (own == "soutien" and trial.rank not in ("E", "D")):
            assert rates[own] >= 0.8, (build_role, rates)
