"""La formule de dégâts unique et les leviers de rôle (25/10/2026).

dégâts = ATK − DEF, au moins 25 % de l'ATK ; la défense au-delà de 75 % de
l'ATK revient à l'attaquant en contrecoup (ni action, ni effet, pas de boucle).
"""

import random

import pytest

from app.domain.services.combat_passives import CombatPassives
from app.domain.services.damage_formula import resolve_hit, thorns_recoil
from app.domain.services.party_combat_service import PartyCombatService
from app.domain.value_objects.stats import Stats
from tests.domain.test_party_combat_service import build_mob


def _stats(hp=1000, atk=100, dfn=0, speed=10) -> Stats:
    return Stats(max_hp=hp, attack=atk, defense=dfn, speed=speed, crit_chance=0,
                 crit_damage=150, dodge=0, hp_regeneration=0, mana_max=0, mana_regeneration=0)


def _member(pid, stats, hp=None):
    return {"player_id": pid, "user_id": pid, "name": f"J{pid}", "avatar_url": "",
            "stats": stats, "current_hp": stats.max_hp if hp is None else hp,
            "max_hp": stats.max_hp}


def _contrib(result, pid):
    return next(c for c in result.contributions if c.player_id == pid)


# ------------------------------------------------------------ formule --
@pytest.mark.parametrize("atk, dfn, dmg, recoil", [
    (100, 40, 60, 0),     # sous 75 % : exactement l'ancien ATK − DEF
    (100, 75, 25, 0),     # pile au plafond : 25 % passent, rien ne revient
    (100, 100, 25, 25),   # ATK = DEF : 25 % passent, 25 reviennent
    (100, 300, 25, 225),  # mur : toujours 25 %, le surplus revient
    (1, 0, 1, 0),         # plancher absolu de 1
])
def test_formule_unique(atk, dfn, dmg, recoil):
    assert resolve_hit(atk, dfn) == (dmg, recoil)


def test_epines_dix_pour_cent_de_contrecoup_en_plus():
    assert thorns_recoil(100, True) == 110
    assert thorns_recoil(100, False) == 100
    assert thorns_recoil(0, True) == 0


# ------------------------------------------------------------ contrecoup --
def test_le_contrecoup_ne_compte_pas_comme_une_action():
    random.seed(0)
    mob = build_mob(current_hp=10**6, max_hp=10**6, attack=100, defense=0, speed=10)
    tank = _stats(hp=100_000, atk=1, dfn=300, speed=1)
    result = PartyCombatService().fight_party_vs_mob([_member(1, tank)], mob, max_turns=10)
    hits = [t for t in result.turn_logs if "contrecoup" in t.mob_action]
    assert hits, "le tank renvoie le surplus de sa défense"
    # 300 − 75 = 225 renvoyés par coup, dans la ligne du coup du monstre :
    # aucune entrée de journal ni action en plus.
    assert all("🔁 225 en contrecoup" in t.mob_action for t in hits)
    assert result.turns == len(result.turn_logs)
    # Hors contrecoup, le tank (ATK 1, vitesse 1) n'inflige presque rien.
    assert 225 * len(hits) <= _contrib(result, 1).damage_dealt <= 225 * len(hits) + 2


def test_le_contrecoup_ne_declenche_pas_d_effet():
    """Riposte, vol de vie, fureur : rien ne part d'un contrecoup."""
    random.seed(0)
    mob = build_mob(current_hp=10**6, max_hp=10**6, attack=1, defense=300, speed=1)
    striker = _stats(hp=100_000, atk=100, dfn=0, speed=100)
    passives = {1: CombatPassives(lifesteal_pct=50, gear=frozenset({"rising_fury"}))}
    result = PartyCombatService().fight_party_vs_mob(
        [_member(1, striker, hp=50_000)], mob, max_turns=5, passives_by_player=passives)
    # 300 − 75 = 225 de contrecoup à chaque coup ; le vol de vie ne soigne que
    # sur les dégâts INFLIGÉS (25), jamais sur le contrecoup subi.
    actions = [a for t in result.turn_logs for a in t.player_actions]
    assert actions and all("🔁" in a for a in actions)
    assert _contrib(result, 1).final_hp < 50_000


def test_pas_de_boucle_le_monstre_ne_renvoie_pas_le_contrecoup():
    random.seed(0)
    # Les deux ont une énorme défense : chacun renvoie le surplus, mais un
    # contrecoup ne provoque jamais de contrecoup en retour.
    mob = build_mob(current_hp=10**6, max_hp=10**6, attack=100, defense=1000, speed=10)
    wall = _stats(hp=10**6, atk=100, dfn=1000, speed=10)
    result = PartyCombatService().fight_party_vs_mob([_member(1, wall)], mob, max_turns=4)
    assert result.turns == 4


def test_le_contrecoup_peut_achever_le_monstre_et_declenche_sa_resurrection():
    random.seed(0)
    mob = build_mob(current_hp=50, max_hp=1000, attack=100, defense=0, speed=100)
    tank = _stats(hp=10**6, atk=1, dfn=300, speed=1)
    result = PartyCombatService().fight_party_vs_mob(
        [_member(1, tank)], mob, max_turns=3, mob_abilities={"revive": {"atk_pct": 0}})
    assert any("renaît" in t.mob_action for t in result.turn_logs)


def test_charme_meme_formule_contrecoup_compris():
    random.seed(1)
    svc = PartyCombatService()
    svc._passives = {}
    contributions = {1: type("C", (), {"damage_tanked": 0, "dodges": 0})(),
                     2: type("C", (), {"damage_tanked": 0, "dodges": 0})()}
    a = {"player_id": 1, "stats": _stats(atk=100), "hp": 1000, "max_hp": 1000, "shield": 0}
    b = {"player_id": 2, "stats": _stats(dfn=200), "hp": 1000, "max_hp": 1000, "shield": 0}
    dmg, _, dodged, recoil = svc._pvp_hit(a, b, contributions)
    assert (dmg, dodged, recoil) == (25, False, 125)
    assert a["hp"] == 1000 - 125


# ---------------------------------------------------------------- aggro --
def test_aggro_le_plus_solide_prend_la_majorite_des_coups():
    mob = build_mob(current_hp=10**9, max_hp=10**9, attack=10, defense=0, speed=100)
    tank = _stats(hp=100_000, atk=1, dfn=0, speed=1)
    dps = _stats(hp=50_000, atk=1, dfn=0, speed=1)
    on_tank = on_dps = 0
    for seed in range(20):   # 20 combats de 20 coups, sous l'escalade
        random.seed(seed)
        result = PartyCombatService().fight_party_vs_mob(
            [_member(1, tank), _member(2, dps)], mob, max_turns=20)
        on_tank += _contrib(result, 1).damage_tanked
        on_dps += _contrib(result, 2).damage_tanked
    # Robustesse ×2 ⇒ poids ×8 : ~89 % des coups sur le tank.
    assert on_tank > 5 * on_dps


# ----------------------------------------------------------------- aura --
def test_aura_du_soigneur_une_seule_par_equipe():
    def dealt(passives):
        random.seed(0)
        mob = build_mob(current_hp=10**9, max_hp=10**9, attack=0, defense=0, speed=1)
        party = [_member(1, _stats(atk=100, speed=100)), _member(2, _stats(atk=1, speed=1)),
                 _member(3, _stats(atk=1, speed=1))]
        result = PartyCombatService().fight_party_vs_mob(
            party, mob, max_turns=1, passives_by_player=passives)
        return _contrib(result, 1).damage_dealt

    aura = CombatPassives(team_damage_pct=25)
    assert dealt({}) == 100
    assert dealt({2: aura}) == 125
    assert dealt({2: aura, 3: aura}) == 125   # deux Soigneurs : toujours +25 %


# ------------------------------------------------------------------ soin --
def test_le_soigneur_attaque_si_personne_n_est_sous_cinquante_pour_cent():
    mob = build_mob(current_hp=10**9, max_hp=10**9, attack=0, defense=0, speed=1)
    party = [_member(1, _stats(atk=100, speed=100)), _member(2, _stats(atk=1, speed=1), hp=600)]
    result = PartyCombatService().fight_party_vs_mob(
        party, mob, max_turns=1,
        passives_by_player={1: CombatPassives(healer=True, heal_power_multiplier=2)})
    assert _contrib(result, 1).damage_dealt == 100
    assert _contrib(result, 2).final_hp == 600


# ------------------------------------------------------------- escalade --
def test_l_escalade_compte_les_actions_du_monstre_pas_celles_du_groupe():
    random.seed(0)
    mob = build_mob(current_hp=10**9, max_hp=10**9, attack=1, defense=0, speed=1)
    party = [_member(i, _stats(hp=10**6, atk=1, speed=100)) for i in (1, 2, 3)]
    result = PartyCombatService().fight_party_vs_mob(party, mob, max_turns=400)
    # 400 actions des joueurs, à peine quelques-unes du monstre : pas d'escalade.
    assert not any("s'éternise" in t.mob_action for t in result.turn_logs)


# ------------------------------------------------------- garde offensive --
def test_garde_offensive_la_defense_s_ajoute_a_l_attaque():
    from app.domain.services.stats_service import StatsService
    from app.domain.value_objects.skill_bonuses import SkillBonuses
    from tests.domain.test_stats_service import build_profile

    profile = build_profile(level=11, points_defense=10)
    plain = StatsService().calculate_player_stats(profile, [], skill_bonuses=SkillBonuses())
    guard = StatsService().calculate_player_stats(
        profile, [], skill_bonuses=SkillBonuses(defense_to_attack_percent=1.0))
    assert guard.defense == plain.defense
    assert guard.attack == plain.attack + plain.defense


def test_cases_de_vitesse_a_demi_point():
    from app.domain.services.stats_service import StatsService
    from app.domain.value_objects.skill_bonuses import SkillBonuses
    from tests.domain.test_stats_service import build_profile

    profile = build_profile(level=1)
    base = StatsService().calculate_player_stats(profile, [], skill_bonuses=SkillBonuses())
    three_nodes = StatsService().calculate_player_stats(
        profile, [], skill_bonuses=SkillBonuses(speed_flat=1.5))
    assert three_nodes.speed == base.speed + 1   # tronquée : 1,5 → +1
