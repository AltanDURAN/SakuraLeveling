"""Coût en mana des compétences actives (calibré le 25/10/2026,
`scripts/measure_mana.py`) : le mana limite les combats difficiles sans
changer leur issue, et le farm ne le vide jamais."""

import importlib.util
import json
import random
import statistics
import sys
from pathlib import Path

import pytest

from app.domain.services.mob_ability_service import GROUP_ELITES, get_mob_abilities
from app.domain.services.party_combat_service import PartyCombatService

_ROOT = Path(__file__).resolve().parents[2]


def _load(name: str):
    # Chargé par son chemin : le dossier tests/scripts masque le paquet `scripts`.
    spec = importlib.util.spec_from_file_location(name, _ROOT / f"scripts/{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module   # requis par les dataclasses du module
    spec.loader.exec_module(module)
    return module


ROLES = sys.modules.get("reference_roles") or _load("reference_roles")
RESTAT = sys.modules.get("restat_mobs") or _load("restat_mobs")
MOBS = {m["code"]: m for m in json.loads(
    (_ROOT / "app/infrastructure/content/mobs.json").read_text(encoding="utf-8"))}


def _fights(compo: str, level: int, mob, abilities: dict, n: int):
    results = []
    for seed in range(n):
        random.seed(seed)
        members, passives, tactics = ROLES.party(compo, level)
        results.append(PartyCombatService().fight_party_vs_mob(
            members, mob, mob_abilities=abilities, passives_by_player=passives,
            tactics_by_player=tactics))
    return results


def _elite(code: str):
    m = MOBS[code]
    return RESTAT.as_mob(code, {k: m.get(k, d) for k, d in (
        ("max_hp", 0), ("attack", 0), ("defense", 0), ("speed", 5),
        ("crit_chance", 0), ("crit_damage", 100), ("dodge", 0))})


def test_une_elite_vide_la_reserve_du_soigneur_sans_changer_l_issue():
    spent = []
    for code in GROUP_ELITES:
        level = RESTAT.ASSIGN[code][0]
        results = _fights("DTS", level, _elite(code), get_mob_abilities(code), n=10)
        assert sum(r.victory for r in results) / len(results) >= 0.9, code
        support = [next(c for c in r.contributions if c.player_id == 3) for r in results]
        spent.append(statistics.mean(c.mana_spent / c.mana_max for c in support))
    # Le mana compte : un combat d'élite consomme l'essentiel de la réserve.
    assert statistics.median(spent) >= 0.5, spent


@pytest.mark.parametrize("level", (30, 60, 100))
@pytest.mark.parametrize("compo", ("D", "T", "S", "G", "DTS", "GGG"))
def test_le_farm_ne_vide_pas_la_reserve(compo, level):
    mob = RESTAT.as_mob("standard", RESTAT.restat(level, "standard"))
    results = _fights(compo, level, mob, {}, n=8)
    for pid, letter in enumerate(compo, 1):
        regen = ROLES.build(ROLES.ROLE_OF[letter], level).stats.mana_regeneration
        spent = statistics.mean(next(c for c in r.contributions if c.player_id == pid).mana_spent
                                for r in results)
        assert spent <= 3 * regen, (letter, spent)   # 3 min par combat de farm
