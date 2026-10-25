"""Équilibrage des monstres, mesuré avec le VRAI moteur de combat.

Invariants de progression (audit d'octobre 2026) :
  • un compte NEUF (niveau 1, aucun équipement) bat le premier monstre — avant,
    il perdait 100 % de ses combats, même contre un slime ;
  • chaque monstre est battu en solo par le joueur de référence de son palier.
    Les « blindés » duraient ~95 actions : l'escalade (action 50) les rendait
    imbattables, même à leur propre niveau ;
  • chaque ÉLITE DE GROUPE (25/10/2026) est battue par le trio DPS + Tank +
    Support de son niveau, capacités comprises, mais pas par un DPS seul.
"""

import json
import random
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.domain.entities.mob_definition import MobDefinition
from app.domain.services.mob_ability_service import GROUP_ELITES, get_mob_abilities, is_group_elite
from app.domain.services.party_combat_service import PartyCombatService
from app.domain.services.reference_player import reference_stats
_ROOT = Path(__file__).resolve().parents[2]


def _load(name: str):
    # Chargé par son chemin : le dossier tests/scripts masque le paquet `scripts`.
    import importlib.util

    import sys

    spec = importlib.util.spec_from_file_location(name, _ROOT / f"scripts/{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module   # requis par les dataclasses du module
    spec.loader.exec_module(module)
    return module


ASSIGN = _load("restat_mobs").ASSIGN
ROLES = _load("reference_roles")

MOBS = {
    m["code"]: m
    for m in json.loads(
        (_ROOT / "app/infrastructure/content/mobs.json")
        .read_text(encoding="utf-8")
    )
}


def _mob(code: str) -> MobDefinition:
    m = MOBS[code]
    now = datetime.now(UTC)
    return MobDefinition(
        id=0, code=code, name=m.get("name", code), description="", image_name="",
        family=m.get("family", ""), max_hp=m["max_hp"], current_hp=m["max_hp"],
        attack=m["attack"], defense=m["defense"], xp_reward=0, gold_reward=0,
        spawn_weight=1, speed=m.get("speed", 5), crit_chance=m.get("crit_chance", 0),
        crit_damage=m.get("crit_damage", 100), dodge=m.get("dodge", 0),
        hp_regeneration=0, loot_table=None, created_at=now, updated_at=now, element="",
    )


def _win_rate(player, mob, n=30) -> float:
    service = PartyCombatService()
    wins = 0
    for seed in range(n):
        random.seed(seed)
        party = [{
            "player_id": 1, "user_id": 1, "name": "p", "avatar_url": "", "stats": player,
            "current_hp": player.max_hp, "max_hp": player.max_hp,
            "current_mana": player.mana_max, "mana_max": player.mana_max,
        }]
        wins += service.fight_party_vs_mob(party, mob).victory
    return wins / n


def test_un_compte_neuf_bat_le_premier_monstre():
    first = min(ASSIGN, key=lambda code: ASSIGN[code][0])
    naked = reference_stats(1, gear_percent=0)
    assert _win_rate(naked, _mob(first)) >= 0.9


@pytest.mark.parametrize("code", sorted(c for c in ASSIGN if c in MOBS and not is_group_elite(c)))
def test_chaque_monstre_est_battu_a_son_palier(code):
    level, archetype = ASSIGN[code]
    assert _win_rate(reference_stats(level), _mob(code)) >= 0.8, (
        f"{code} ({archetype}, palier {level}) imbattable par le joueur de référence"
    )


@pytest.mark.parametrize("code", sorted(GROUP_ELITES))
def test_chaque_elite_est_battue_par_le_trio_mais_pas_en_solo(code):
    level, _ = ASSIGN[code]
    mob, abilities = _mob(code), get_mob_abilities(code)
    trio = ROLES.fight("DTS", level, mob, abilities, n=10)
    assert trio["win"] >= 0.9, f"{code} : le trio de son niveau ne gagne que {trio['win']:.0%}"
    solo = ROLES.fight("D", level, mob, abilities, n=10)
    assert solo["win"] <= 0.2, f"{code} : un DPS seul gagne {solo['win']:.0%} — ce n'est pas une élite"
