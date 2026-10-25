"""Arbre à trois niveaux de classes (étape 3 de la refonte des rôles,
25/10/2026) : classes de base cumulables, spécialisations exclusives derrière
un seuil de points dans leur voie, arbre plus grand que les points."""

import random

from app.domain.services.combat_passives import CombatPassives
from app.domain.services.party_combat_service import PartyCombatService
from app.domain.services.skill_tree_service import SkillTreeService
from app.domain.value_objects.stats import Stats
from app.infrastructure.skill_tree.skill_tree_loader import get_definition, parse_definition
from tests.domain.test_party_combat_service import build_mob


def _tree():
    return parse_definition({
        "roots": ["r"],
        "nodes": {
            "r": {"name": "Racine", "start": True, "max_level": 1, "costs": [0], "effects": []},
            "va": {"name": "Voie A", "max_level": 1, "costs": [1], "effects": []},
            "vb": {"name": "Voie B", "max_level": 1, "costs": [1], "effects": []},
            "a1": {"name": "A1", "max_level": 1, "costs": [3], "effects": []},
            "a2": {"name": "A2", "max_level": 1, "costs": [3], "effects": []},
            "spe_a": {"name": "Spé A", "max_level": 1, "costs": [2], "effects": [],
                      "exclusive_group": "spécialisation", "voie_requirement": {"voie": "va", "points": 7}},
            "spe_b": {"name": "Spé B", "max_level": 1, "costs": [2], "effects": [],
                      "exclusive_group": "spécialisation", "voie_requirement": {"voie": "vb", "points": 1}},
        },
        "links": [{"from": "r", "to": "va"}, {"from": "r", "to": "vb"}, {"from": "va", "to": "a1"},
                  {"from": "a1", "to": "a2"}, {"from": "va", "to": "spe_a"}, {"from": "vb", "to": "spe_b"}],
    })


def test_le_seuil_de_voie_compte_les_points_investis_dans_la_voie():
    svc = SkillTreeService(_tree())
    alloc = {"va": 1, "a1": 1}
    assert svc.voie_points(alloc, "va") == 4
    spe = svc.definition.get("spe_a")
    assert "7 points dans la Voie A requis (4/7)" in svc.rule_lock(alloc, spe)
    assert spe not in svc.compute_unlockable_skills(alloc)
    ok, message, _ = svc.validate_investment(alloc, 10, "spe_a")
    assert not ok and "verrouillé" in message
    alloc["a2"] = 1
    assert svc.rule_lock(alloc, spe) is None
    assert svc.validate_investment(alloc, 10, "spe_a")[0]


def test_une_seule_specialisation():
    svc = SkillTreeService(_tree())
    alloc = {"va": 1, "a1": 1, "a2": 1, "vb": 1, "spe_a": 1}
    lock = svc.rule_lock(alloc, svc.definition.get("spe_b"))
    assert lock and "déjà Spé A" in lock
    assert svc.compute_node_state(alloc, "spe_b") == "locked"


def test_l_arbre_du_jeu_a_trois_niveaux_de_classes():
    definition = get_definition()
    svc = SkillTreeService(definition)
    specs = {n.code for n in definition if n.exclusive_group == "spécialisation"}
    assert specs == {"passif_25", "passif_20", "passif_16"}   # Assassin, Rempart, Soigneur
    for code in specs:
        req = definition.get(code).voie_requirement
        assert req and req["points"] >= 20 and code in svc.voie_codes(req["voie"])
    bases = [definition.get(c) for c in ("base_guerrier", "base_gardien", "base_clerc")]
    assert all(b is not None and not b.exclusive_group for b in bases)
    combat = sum(n.cumulative_cost(n.max_level) for n in definition
                 if not n.start and n.node_type != "utilite")
    assert combat > 2 * 99    # un joueur n'en a que la moitié au niveau 100


def test_le_clerc_soigne_l_allie_le_plus_blesse_avec_ses_degats():
    random.seed(0)
    mob = build_mob(current_hp=10**9, max_hp=10**9, attack=0, defense=0, speed=1)

    def member(pid, hp):
        st = Stats(max_hp=1000, attack=100, defense=0, speed=100 if pid == 1 else 1, crit_chance=0,
                   crit_damage=150, dodge=0, hp_regeneration=0, mana_max=0, mana_regeneration=0)
        return {"player_id": pid, "user_id": pid, "name": f"J{pid}", "avatar_url": "", "stats": st,
                "current_hp": hp, "max_hp": 1000}

    result = PartyCombatService().fight_party_vs_mob(
        [member(1, 1000), member(2, 500)], mob, max_turns=1,
        passives_by_player={1: CombatPassives(ally_heal_on_hit_pct=20)})
    clerc, ally = (next(c for c in result.contributions if c.player_id == p) for p in (1, 2))
    assert clerc.damage_dealt == 100            # il attaque normalement…
    assert ally.final_hp == 520 and clerc.hp_healed == 20   # …et 20 % soignent l'allié


def test_le_gardien_attire_les_coups():
    mob = build_mob(current_hp=10**9, max_hp=10**9, attack=10, defense=0, speed=100)

    def member(pid):
        st = Stats(max_hp=10_000, attack=1, defense=0, speed=1, crit_chance=0, crit_damage=150,
                   dodge=0, hp_regeneration=0, mana_max=0, mana_regeneration=0)
        return {"player_id": pid, "user_id": pid, "name": f"J{pid}", "avatar_url": "", "stats": st,
                "current_hp": 10_000, "max_hp": 10_000}

    on_guard = on_other = 0
    for seed in range(20):
        random.seed(seed)
        result = PartyCombatService().fight_party_vs_mob(
            [member(1), member(2)], mob, max_turns=20,
            passives_by_player={1: CombatPassives(threat_pct=50)})
        on_guard += next(c.damage_tanked for c in result.contributions if c.player_id == 1)
        on_other += next(c.damage_tanked for c in result.contributions if c.player_id == 2)
    assert on_guard > 2.5 * on_other   # 1,5³ ≈ 3,4 fois plus visé
