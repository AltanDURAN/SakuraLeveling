"""Événements d'affichage du moteur (chiffres et effets de combat, 27/10/2026) :
ils décrivent fidèlement ce qui s'est passé, sans rien changer au combat."""

import random

from app.domain.services.party_combat_service import PartyCombatService
from tests.domain.test_gear_passives_combat import CombatPassives, fight, member, mob


def _events(result, kind=None):
    return [e for log in result.turn_logs for e in log.events if kind is None or e["kind"] == kind]


def test_chaque_coup_porte_sur_l_ennemi_a_son_evenement():
    res = fight([member()], mob(attack=1, speed=0), max_turns=5)
    hits = [e for e in _events(res) if e["kind"] in ("hit", "crit") and e["target"] == "e0"]
    assert len(hits) == 5 and all(e["source"] == "p1" and e["amount"] == 90 for e in hits)
    assert sum(e["amount"] for e in hits) == res.contributions[0].damage_dealt


def test_critiques_esquives_soins_et_boucliers():
    crit = fight([member(crit_chance=100)], mob(attack=1, speed=0), max_turns=1)
    assert _events(crit, "crit")[0]["amount"] == 190
    dodge = fight([member(dodge=100, max_hp=10**6)], mob(attack=50, speed=20), max_turns=4)
    assert _events(dodge, "dodge") and all(e["target"] == "p1" for e in _events(dodge, "dodge"))
    hurt = [{**member(), "current_hp": 100}]
    heal = fight(hurt, mob(attack=1, speed=0), {1: CombatPassives(lifesteal_pct=50)}, max_turns=1)
    assert _events(heal, "heal") == [{"kind": "heal", "target": "p1", "amount": 45, "source": "p1"}]
    shield = fight([member(), member(2)], mob(attack=1, speed=0), {1: CombatPassives(team_shield_pct=10)},
                   max_turns=1)
    assert {e["target"] for e in _events(shield, "shield")} == {"p1", "p2"}


def test_les_coups_du_monstre_et_le_ko():
    res = fight([member(max_hp=200, defense=0)], mob(attack=150, speed=30), max_turns=10)
    hits = [e for e in _events(res) if e["kind"] in ("hit", "crit") and e["target"] == "p1"]
    assert hits and all(e["source"] == "e0" and e["style"] == "melee" for e in hits)
    assert _events(res, "ko")[-1]["target"] == "p1"


def test_les_evenements_ne_changent_pas_le_combat():
    """Pur enregistrement : sans aucun tirage en plus, deux combats à la même
    graine sont identiques, et chaque instantané ne garde que SES événements."""
    random.seed(11)
    a = PartyCombatService().fight_party_vs_mob([member(crit_chance=30, dodge=10)], mob(attack=120, dodge=10))
    random.seed(11)
    b = PartyCombatService().fight_party_vs_mob([member(crit_chance=30, dodge=10)], mob(attack=120, dodge=10))
    assert a.turns == b.turns and [log.events for log in a.turn_logs] == [log.events for log in b.turn_logs]
    assert sum(len(log.events) for log in a.turn_logs) >= a.turns
