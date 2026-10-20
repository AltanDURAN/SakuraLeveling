"""Chaque world boss se tue en une semaine de raid par une équipe de son niveau.

Mesuré avec le vrai moteur, capacités comprises (soin, immunité, renvoi,
invocations, escalade). Avant l'audit d'octobre 2026, le Titan (le boss
d'ouverture) et le Dragon encaissaient 0 dégât net : leurs soins, appliqués à
chaque tick au lieu de chaque tour, annulaient tout le raid.
"""

import importlib.util
import json
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("restat_bosses", _ROOT / "scripts/restat_bosses.py")
RB = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(RB)

BOSSES = json.loads((_ROOT / "app/infrastructure/content/boss_definitions.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("boss", BOSSES, ids=[b["code"] for b in BOSSES])
def test_boss_tue_en_une_semaine_par_une_equipe_de_son_niveau(boss):
    level = RB.TARGET_LEVEL[boss["code"]]
    per_assault = RB._measure_damage_per_assault(level, boss["attack"], boss["defense"], boss)
    assert per_assault > 0, f"{boss['code']} : aucun dégât net — ses capacités annulent le raid"
    assaults = boss["max_hp"] / per_assault
    assert 4 <= assaults <= 9, f"{boss['code']} : {assaults:.1f} assauts pour le tuer"
