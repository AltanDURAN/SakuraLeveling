"""Passifs de combat et classes de l'arbre (saison 1).

Chaque test isole un effet : stats sans hasard (0 % crit, 0 % esquive) pour
que le résultat soit déterministe.
"""

import pytest

from app.domain.services.combat_passives import (
    CombatPassives,
    mage_multiplier,
    outgoing_elemental_multiplier,
)
from app.domain.services.party_combat_service import PartyCombatService
from app.domain.value_objects.stats import Stats
from tests.domain.test_party_combat_service import build_mob


def _stats(hp=1000, atk=50, dfn=10, speed=50, crit=0, crit_dmg=150) -> Stats:
    return Stats(max_hp=hp, attack=atk, defense=dfn, speed=speed, crit_chance=crit,
                 crit_damage=crit_dmg, dodge=0, hp_regeneration=0, mana_max=100,
                 mana_regeneration=5)


def _member(pid, stats=None, hp=None, name=None):
    stats = stats or _stats()
    return {"player_id": pid, "user_id": pid, "name": name or f"J{pid}", "avatar_url": "",
            "stats": stats, "current_hp": stats.max_hp if hp is None else hp,
            "max_hp": stats.max_hp}


def _contrib(result, pid):
    return next(c for c in result.contributions if c.player_id == pid)


# ------------------------------------------------------------------ Mage --
@pytest.mark.parametrize("aff, mult", [(0, 1.0), (24, 1.0), (25, 1.25), (50, 1.5), (99, 1.5), (100, 2.0)])
def test_mage_paliers(aff, mult):
    assert mage_multiplier(aff) == mult


def test_mage_sans_infusion_pas_de_bonus():
    mage = CombatPassives(mage=True)
    assert outgoing_elemental_multiplier(1.0, "", {"feu": 100}, mage) == 1.0
    # Le Mage amplifie le GAIN : 1 + 0,2 × 1,5.
    assert outgoing_elemental_multiplier(1.2, "feu", {"feu": 50}, mage) == pytest.approx(1.3)
    assert outgoing_elemental_multiplier(1.6, "feu", {"feu": 100}, mage) == pytest.approx(2.2)


# ------------------------------------------------------- dégâts et défense --
def test_titan_et_lethal_augmentent_les_degats():
    mob = build_mob(current_hp=100_000, max_hp=100_000, attack=0, defense=30, speed=1)
    base = PartyCombatService().fight_party_vs_mob([_member(1)], mob, max_turns=3)
    boosted = PartyCombatService().fight_party_vs_mob(
        [_member(1)], mob, max_turns=3,
        passives_by_player={1: CombatPassives(damage_dealt_pct=5, armor_penetration_pct=10)},
    )
    # Base : 50 − 30 = 20 par coup. Léthal : défense 27 → 23 ; Titan ×1,05 → 24.
    assert _contrib(base, 1).damage_dealt == 60
    assert _contrib(boosted, 1).damage_dealt == 72


def test_reduction_des_degats_recus_s_additionne():
    mob = build_mob(current_hp=10**9, max_hp=10**9, attack=110, defense=0, speed=50)
    passives = {1: CombatPassives(damage_taken_reduction_pct=15)}
    result = PartyCombatService().fight_party_vs_mob(
        [_member(1, _stats(atk=1, speed=1))], mob, max_turns=2, passives_by_player=passives,
    )
    # 110 − 10 de défense = 100, −15 % → 85 par coup.
    assert 1000 - _contrib(result, 1).final_hp == 85 * 2


# ------------------------------------------------------------ Tenace --
def test_tenace_survit_au_premier_coup_fatal_seulement():
    mob = build_mob(current_hp=10**9, max_hp=10**9, attack=5000, defense=0, speed=100)
    result = PartyCombatService().fight_party_vs_mob(
        [_member(1, _stats(atk=1, speed=1))], mob, max_turns=1,
        passives_by_player={1: CombatPassives(last_stand=True)},
    )
    assert _contrib(result, 1).final_hp == 1
    assert any("tient bon" in log.mob_action for log in result.turn_logs)

    dead = PartyCombatService().fight_party_vs_mob(
        [_member(1, _stats(atk=1, speed=1))], mob, max_turns=5,
        passives_by_player={1: CombatPassives(last_stand=True)},
    )
    assert not _contrib(dead, 1).survived


# ------------------------------------------------------------ Vampire --
def test_vampire_se_soigne_des_degats_infliges():
    mob = build_mob(current_hp=10**6, max_hp=10**6, attack=0, defense=0, speed=1)
    result = PartyCombatService().fight_party_vs_mob(
        [_member(1, _stats(atk=200), hp=500)], mob, max_turns=1,
        passives_by_player={1: CombatPassives(lifesteal_pct=5, heal_received_pct=50)},
    )
    # 200 dégâts → 10 PV volés, ×1,5 (soins reçus du Paladin) = 15.
    assert _contrib(result, 1).final_hp == 515


# -------------------------------------------------------------- Égide --
def test_egide_donne_un_bouclier_a_tout_le_groupe():
    mob = build_mob(current_hp=10**9, max_hp=10**9, attack=60, defense=0, speed=50)
    party = [_member(1, _stats(atk=1, speed=1)), _member(2, _stats(atk=1, speed=1))]
    result = PartyCombatService().fight_party_vs_mob(
        party, mob, max_turns=1, passives_by_player={1: CombatPassives(team_shield_pct=10)},
    )
    assert "Égide" in result.turn_logs[0].mob_action
    # Bouclier de 100 (10 % de 1 000) : le coup de 50 est absorbé.
    assert sum(1000 - _contrib(result, p).final_hp for p in (1, 2)) == 0
    assert _contrib(result, 1).hp_healed == 100  # bouclier donné à l'allié


# ------------------------------------------------------------ Rempart --
def test_rempart_encaisse_la_moitie_des_coups_des_allies(monkeypatch):
    mob = build_mob(current_hp=10**9, max_hp=10**9, attack=110, defense=0, speed=50)
    party = [_member(1, _stats(atk=1, speed=1)), _member(2, _stats(atk=1, speed=1))]
    # Le monstre vise toujours le joueur 2.
    monkeypatch.setattr("random.choice", lambda pool: pool[-1])
    result = PartyCombatService().fight_party_vs_mob(
        party, mob, max_turns=1,
        passives_by_player={1: CombatPassives(redirect_ally_damage_pct=50)},
    )
    assert 1000 - _contrib(result, 2).final_hp == 50
    assert 1000 - _contrib(result, 1).final_hp == 50


# ------------------------------------------------------------ Vaillant --
def test_vaillant_attire_le_prochain_coup(monkeypatch):
    mob = build_mob(current_hp=10**9, max_hp=10**9, attack=110, defense=0, speed=50)
    party = [_member(1, _stats(speed=100)), _member(2, _stats(atk=1, speed=1))]
    monkeypatch.setattr("random.choice", lambda pool: pool[-1])  # sinon : joueur 2
    result = PartyCombatService().fight_party_vs_mob(
        party, mob, max_turns=3,
        passives_by_player={1: CombatPassives(taunt_chance_pct=100)},
    )
    assert _contrib(result, 1).final_hp < 1000
    assert _contrib(result, 2).final_hp == 1000


# ----------------------------------------------- Soigneur et tactiques --
def _heal_fight(tactic, monkeypatch=None):
    mob = build_mob(current_hp=10**9, max_hp=10**9, attack=0, defense=0, speed=1)
    party = [
        _member(1, _stats(atk=100, speed=100), name="Soigneur"),
        _member(2, _stats(atk=1, speed=1), hp=500, name="Tank"),
        _member(3, _stats(atk=1, speed=1), hp=200, name="Mage"),
    ]
    return PartyCombatService().fight_party_vs_mob(
        party, mob, max_turns=1,
        passives_by_player={1: CombatPassives(healer=True, heal_power_multiplier=2)},
        tactics_by_player={1: tactic},
    )


def test_soigneur_remplace_son_attaque_par_un_soin():
    result = _heal_fight("egoiste")
    assert _contrib(result, 1).damage_dealt == 0
    # Égoïste, déjà au maximum → l'allié le plus blessé (en %) : le Mage.
    # Soin = 100 d'attaque × 50 % × 2 = 100.
    assert _contrib(result, 3).final_hp == 300
    assert _contrib(result, 1).hp_healed == 100


def test_soigneur_egoiste_se_soigne_d_abord():
    mob = build_mob(current_hp=10**9, max_hp=10**9, attack=0, defense=0, speed=1)
    party = [_member(1, _stats(atk=100, speed=100), hp=400), _member(2, _stats(atk=1, speed=1), hp=100)]
    result = PartyCombatService().fight_party_vs_mob(
        party, mob, max_turns=1,
        passives_by_player={1: CombatPassives(healer=True, heal_power_multiplier=2)},
        tactics_by_player={1: "egoiste"},
    )
    assert _contrib(result, 1).final_hp == 500
    assert _contrib(result, 1).hp_healed == 0  # se soigner ne compte pas


def test_soigneur_sans_blesse_attaque():
    mob = build_mob(current_hp=10**6, max_hp=10**6, attack=0, defense=0, speed=1)
    result = PartyCombatService().fight_party_vs_mob(
        [_member(1, _stats(atk=100, speed=100))], mob, max_turns=1,
        passives_by_player={1: CombatPassives(healer=True)},
    )
    assert _contrib(result, 1).damage_dealt == 100


def test_buff_de_soin_non_cumulable():
    mob = build_mob(current_hp=10**9, max_hp=10**9, attack=0, defense=0, speed=1)
    party = [_member(1, _stats(atk=100, speed=300)), _member(2, _stats(atk=100, speed=1), hp=100)]
    result = PartyCombatService().fight_party_vs_mob(
        party, mob, max_turns=3,
        passives_by_player={1: CombatPassives(healer=True, heal_buff_pct=10)},
    )
    attacks = [p["attack"] for log in result.turn_logs for p in log.players_state if p["player_id"] == 2]
    assert max(attacks) == 110  # +10 % une seule fois, malgré plusieurs soins


def test_soigneur_gagne_de_la_vitesse_par_allie():
    mob = build_mob(current_hp=10**6, max_hp=10**6, attack=0, defense=0, speed=1)
    party = [_member(1, _stats(speed=10)), _member(2), _member(3)]
    result = PartyCombatService().fight_party_vs_mob(
        party, mob, max_turns=1, passives_by_player={1: CombatPassives(speed_per_ally=1)},
    )
    speed = next(p["speed"] for p in result.turn_logs[-1].players_state if p["player_id"] == 1)
    assert speed == 12


# --------------------------------------------- agrégation depuis l'arbre --
def _tree(effects_a, effects_b=(), max_a=1):
    from app.infrastructure.skill_tree.skill_tree_loader import parse_definition

    return parse_definition({
        "nodes": {
            "r": {"name": "R", "start": True, "max_level": 1, "costs": [0], "effects": [],
                  "position": {"x": 0, "y": 0}},
            "a": {"name": "A", "max_level": max_a, "costs": [1] * max_a,
                  "effects": [dict(e) for e in effects_a], "position": {"x": 0, "y": 95}},
            "b": {"name": "B", "max_level": 1, "costs": [1],
                  "effects": [dict(e) for e in effects_b], "position": {"x": 95, "y": 0}},
        },
        "links": [{"from": "r", "to": "a"}, {"from": "r", "to": "b"}],
    })


def test_les_reductions_de_plusieurs_cases_s_additionnent():
    from app.domain.services.skill_tree_service import SkillTreeService

    svc = SkillTreeService(_tree(
        [{"type": "damage_taken_reduction_percent", "values": [10]}],
        [{"type": "damage_taken_reduction_percent", "values": [5]},
         {"type": "grant_class", "values": ["titan"]}],
    ))
    p = svc.combat_passives({"a": 1, "b": 1})
    assert p.damage_taken_reduction_pct == 15
    assert p.classes == ("titan",)
    assert svc.combat_passives({"a": 1}).damage_taken_reduction_pct == 10


def test_une_fonctionnalite_ne_se_debloque_qu_au_maximum():
    from app.domain.services.skill_tree_service import SkillTreeService

    svc = SkillTreeService(_tree(
        [{"type": "unlock_feature", "values": ["notify_events"] * 2}], max_a=2,
    ))
    assert svc.unlocked_features({"a": 1}) == set()
    assert svc.unlocked_features({"a": 2}) == {"notify_events"}


def test_assassin_double_les_chances_et_triple_le_multiplicateur():
    from app.domain.services.stats_service import StatsService
    from app.domain.value_objects.skill_bonuses import SkillBonuses
    from tests.domain.test_stats_service import build_profile

    base = StatsService().calculate_player_stats(profile=build_profile(), equipped_items=[])
    assassin = StatsService().calculate_player_stats(
        profile=build_profile(), equipped_items=[],
        skill_bonuses=SkillBonuses(crit_chance_multiplier=2, crit_damage_multiplier=3),
    )
    assert assassin.crit_chance == base.crit_chance * 2
    assert assassin.crit_damage == base.crit_damage * 3  # 150 % → 450 %


# ----------------------------------------------------- reset hebdomadaire --
def test_reset_de_l_arbre_disponible_lundi_suivant_heure_de_paris():
    from datetime import datetime, UTC
    from zoneinfo import ZoneInfo

    from app.domain.services.cooldown_service import CooldownService

    paris = ZoneInfo("Europe/Paris")
    svc = CooldownService()
    # Dimanche 23h (Paris) → lundi 00h, une heure plus tard.
    sunday = datetime(2026, 10, 18, 23, 0, tzinfo=paris).astimezone(UTC)
    _, nxt = svc.build_weekly_skill_reset_cooldown(sunday)
    assert nxt.astimezone(paris) == datetime(2026, 10, 19, 0, 0, tzinfo=paris)
    # Lundi 00h30 → lundi d'après (passage à l'heure d'hiver le 25/10 compris).
    monday = datetime(2026, 10, 19, 0, 30, tzinfo=paris).astimezone(UTC)
    _, nxt = svc.build_weekly_skill_reset_cooldown(monday)
    assert nxt.astimezone(paris) == datetime(2026, 10, 26, 0, 0, tzinfo=paris)


def test_escalade_cumulee_toutes_les_cinq_actions_du_monstre():
    from app.domain.services.party_combat_service import escalation_multiplier

    assert escalation_multiplier(29) == 1.0
    assert escalation_multiplier(30) == pytest.approx(1.1)
    assert escalation_multiplier(35) == pytest.approx(1.1 * 1.2)
    assert escalation_multiplier(44) == pytest.approx(1.1 * 1.2 * 1.3)


def test_le_monstre_se_renforce_et_finit_le_combat_des_soigneurs():
    """Soin = dégâts reçus au départ : l'escalade du monstre finit par percer."""
    from app.domain.services.party_combat_service import HARD_MAX_TURNS

    mob = build_mob(current_hp=10**9, max_hp=10**9, attack=60, defense=0, speed=50)
    result = PartyCombatService().fight_party_vs_mob(
        [_member(1, _stats(atk=100, speed=50))], mob,
        passives_by_player={1: CombatPassives(healer=True)},
    )
    assert not result.victory
    assert result.turns < HARD_MAX_TURNS  # tombé grâce à l'escalade, pas au garde-fou
    assert any("se renforce" in log.mob_action for log in result.turn_logs)
    # Les PV du monstre ne montent jamais (world boss : PV conservés).
    assert all(log.mob_state["max_hp"] == 10**9 for log in result.turn_logs)


def test_garde_fou_a_500_actions():
    from app.domain.services.party_combat_service import HARD_MAX_TURNS

    assert HARD_MAX_TURNS == 500
