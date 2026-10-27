"""Contenu de la tour (`tower_floors.json`, scripts/build_tower.py) : 100
étages cohérents, et chacun franchissable par le généraliste de son niveau."""

import importlib.util
import json
import random
import sys
from pathlib import Path

import pytest

from app.domain.services import tower_service as ts
from app.domain.services.party_combat_service import PartyCombatService

CONTENT = Path(__file__).resolve().parents[2] / "app/infrastructure/content"
FLOORS = json.loads((CONTENT / "tower_floors.json").read_text(encoding="utf-8"))["floors"]
MOBS = {m["code"] for m in json.loads((CONTENT / "mobs.json").read_text(encoding="utf-8"))}


def _roles():
    if "reference_roles" not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            "reference_roles", CONTENT.parents[2] / "scripts/reference_roles.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules["reference_roles"] = module
        spec.loader.exec_module(module)
    return sys.modules["reference_roles"]


def test_cent_etages_coherents():
    assert [f["floor"] for f in FLOORS] == list(range(1, 101))
    for f in FLOORS:
        assert f["level"] == f["floor"] and f["boss"] == ts.is_boss_floor(f["floor"])
        assert 1 <= len(f["enemies"]) <= 4
        assert {e["code"] for e in f["enemies"]} <= MOBS
        assert "succube" not in {e["code"] for e in f["enemies"]}    # charme = défaite seul
        assert sum(e["boss"] for e in f["enemies"]) == (1 if f["boss"] else 0)


@pytest.mark.parametrize("floor", [1, 5, 10, 23, 40, 58, 75, 90, 100])
def test_le_generaliste_de_son_niveau_franchit_l_etage(floor):
    party = _roles().party
    data = FLOORS[floor - 1]
    wins = 0
    for seed in range(20):
        random.seed(seed)
        members, passives, tactics = party("G", data["level"])
        wins += PartyCombatService().fight_party_vs_mobs(
            members, ts.enemy_setups(data["enemies"]), passives_by_player=passives,
            tactics_by_player=tactics).victory
    assert wins >= 8, f"étage {floor} : {wins}/20"


def test_un_compte_neuf_franchit_le_premier_etage():
    from app.domain.services.reference_player import reference_stats

    naked = reference_stats(1, gear_percent=0)
    member = {"player_id": 1, "user_id": 1, "name": "neuf", "avatar_url": "", "stats": naked,
              "current_hp": naked.max_hp, "max_hp": naked.max_hp,
              "current_mana": naked.mana_max, "mana_max": naked.mana_max}
    wins = 0
    for seed in range(20):
        random.seed(seed)
        wins += PartyCombatService().fight_party_vs_mobs(
            [dict(member)], ts.enemy_setups(FLOORS[0]["enemies"])).victory
    assert wins >= 18
