"""Quêtes adaptées et zones C → A : à l'ouverture des zones (scripts/open_zones),
chaque rang reçoit des quêtes de la famille de SA zone. Vérifié en ouvrant
toutes les zones prévues sur une copie du contenu."""

import copy
import json
from pathlib import Path

import pytest

from app.domain.services import quest_generation_service as qgs
from app.domain.services.mob_ability_service import is_group_elite
from app.infrastructure.encounters import farm_zone_loader as fz

C = Path(__file__).resolve().parents[2] / "app/infrastructure/content"
MOBS = [m for m in json.loads((C / "mobs.json").read_text(encoding="utf-8")) if not is_group_elite(m["code"])]


@pytest.fixture
def all_zones_open(monkeypatch):
    data = copy.deepcopy(fz._load())
    for i, zone in enumerate(data.get("planned_zones", [])):
        zone["channel_id"] = 900 + i
        data["zones"].append(zone)
    data["planned_zones"] = []
    monkeypatch.setattr(fz, "_load", lambda: data)


def _context(rank: str, level: int) -> qgs.QuestContext:
    accessible, families = set(fz.families_for_rank(rank)), []
    for zone in fz.list_zones():
        zone_mobs = [m for m in MOBS if m["family"] in zone["families"]]
        weight = sum(m.get("spawn_weight", 0) for m in zone_mobs) or 1
        for family in zone["families"]:
            own = [m for m in zone_mobs if m["family"] == family]
            if family in accessible and own:
                families.append(qgs.FamilyChoice(
                    family, int(min(m["xp_reward"] / qgs.XP_PER_KILL_PER_LEVEL for m in own)),
                    sum(m.get("spawn_weight", 0) for m in own) / weight))
    return qgs.QuestContext(level=level, roles=frozenset(), families=tuple(families))


@pytest.mark.parametrize("rank,level,family", [
    ("F", 10, "gobelin"), ("E", 25, "mort-vivant"), ("D", 45, "demoniaque"),
    ("C", 50, "primordial"), ("B", 62, "nocturne"), ("A", 75, "draconique"),
])
def test_chaque_rang_vise_la_famille_de_sa_zone(all_zones_open, rank, level, family):
    assert qgs.best_family(_context(rank, level)).family == family
