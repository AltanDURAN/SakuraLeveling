"""Mécaniques de world boss (27/10/2026, A, B et C) : de vraies phases, une
attaque ultime annoncée que la provocation intercepte, des gardes qui
protègent le boss."""

import random

from app.domain.services.boss_assault import GUARDED_REDUCTION_PCT, assault_enemies
from app.domain.services.party_combat_service import PartyCombatService
from tests.domain.test_gear_passives_combat import CombatPassives, member, mob


def assault(party, boss, passives=None, seed=0, **kw):
    fight_kw = {k: kw.pop(k) for k in ("max_turns", "max_ticks") if k in kw}
    enemies, index = assault_enemies(boss, **kw)
    random.seed(seed)
    result = PartyCombatService().fight_party_vs_mobs(party, enemies, passives_by_player=passives or {},
                                                      **fight_kw)
    return result, index


def events(result, kind):
    return [(i, e) for i, log in enumerate(result.turn_logs) for e in log.events or [] if e["kind"] == kind]


def test_les_gardes_encadrent_le_boss():
    guard = {"code": "g", "name": "Garde", "max_hp": 100, "attack": 1}
    enemies, index = assault_enemies(mob(code="boss"), guards=[guard, guard])
    assert index == 1 and [e.mob.code for e in enemies] == ["g", "boss", "g"]
    boss = enemies[index]
    assert boss.is_boss and boss.decisive and boss.guarded_reduction_pct == GUARDED_REDUCTION_PCT
    assert all(e.guard and not e.decisive for e in enemies if e is not boss)
    alone, _ = assault_enemies(mob(code="boss"))
    assert alone[0].guarded_reduction_pct == 0          # sans garde, rien à protéger


def test_une_phase_s_annonce_quand_le_boss_la_franchit():
    boss = mob(code="boss", name="Boss", max_hp=10_000, current_hp=10_000, attack=10, defense=0)
    res, _ = assault([member(1, attack=800)], boss, max_turns=40,
                     phases=[{"below_pct": 75, "name": "Colère", "attack_pct": 50}])
    announced = events(res, "phase")
    assert [e["style"] for _, e in announced] == ["Colère"]
    assert "entre en phase « Colère »" in res.turn_logs[announced[0][0]].mob_action


def test_une_phase_deja_franchie_est_active_d_emblee_sans_annonce():
    def tanked(phases):
        boss = mob(code="boss", max_hp=10_000, current_hp=4_000, attack=300, defense=10**6)
        res, _ = assault([member(1, max_hp=10**6)], boss, phases=phases, max_ticks=300)
        assert not events(res, "phase")
        return res.contributions[0].damage_tanked

    assert tanked([{"below_pct": 75, "name": "Colère", "attack_pct": 100}]) > tanked([])


def test_l_ultime_se_charge_puis_frappe_tout_le_groupe():
    boss = mob(code="boss", max_hp=10**7, current_hp=10**7, attack=200)
    res, _ = assault([member(1, max_hp=10**6), member(2, max_hp=10**6)], boss, max_ticks=600,
                     ultimate={"name": "le Séisme", "every": 3, "multiplier": 2.0})
    charges = events(res, "charge")
    ultimate = [(i, e) for i, log in enumerate(res.turn_logs) for e in log.events or []
                if e.get("style") == "ultimate"]
    assert charges and ultimate and charges[0][0] < ultimate[0][0]
    first = ultimate[0][0]
    assert {e["target"] for i, e in ultimate if i == first} == {"p1", "p2"}


def _ultimate_hits(res) -> dict[int, list[dict]]:
    by_log: dict[int, list[dict]] = {}
    for i, log in enumerate(res.turn_logs):
        for e in log.events or []:
            if e.get("style") == "ultimate":
                by_log.setdefault(i, []).append(e)
    return by_log


def test_le_joueur_en_provocation_intercepte_l_ultime_seul():
    def run(passives):
        boss = mob(code="boss", max_hp=10**7, current_hp=10**7, attack=200)
        party = [member(1, max_hp=10**6), member(2, max_hp=10**6)]
        return assault(party, boss, max_ticks=600, passives=passives,
                       ultimate={"name": "le Séisme", "every": 3, "multiplier": 2.0})[0]

    res = run({1: CombatPassives(taunt_chance_pct=100)})
    by_log = _ultimate_hits(res)
    intercepted = [i for i in by_log if "l'intercepte seul" in res.turn_logs[i].mob_action]
    assert intercepted
    assert all({e["target"] for e in by_log[i]} == {"p1"} for i in intercepted)
    # Seul, il encaisse l'ultime à ×1,5 d'attaque (premier ultime, avant
    # l'escalade ; la défense se retire après : un peu plus que ×1,5 net).
    spread = next(iter(_ultimate_hits(run({})).values()))
    alone = by_log[intercepted[0]][0]["amount"]
    on_tank = next(e["amount"] for e in spread if e["target"] == "p1")
    assert on_tank * 1.5 <= alone <= on_tank * 1.6


def test_les_gardes_protegent_le_boss_tant_qu_ils_tiennent():
    # Le joueur frappe le garde (cible prioritaire) et éclabousse le boss à
    # 100 % : tant que le garde tient, le boss n'en prend que la moitié.
    guard = {"code": "g", "name": "Garde", "max_hp": 10**7, "attack": 1, "defense": 0}
    boss = mob(code="boss", max_hp=10**7, current_hp=10**7, attack=1, defense=0)
    # Défense 0 : pas de contrecoup (il ignore la protection des gardes).
    res, index = assault([member(1, attack=400, defense=0)], boss, guards=[guard], max_turns=10,
                         passives={1: CombatPassives(splash_damage_pct=100)})
    on_guard = 10**7 - res.enemies[0]["remaining_hp"]
    on_boss = 10**7 - res.enemies[index]["remaining_hp"]
    assert on_guard > 0 and abs(on_boss - on_guard / 2) <= 10


def test_l_assaut_se_gagne_sur_le_boss_meme_si_un_garde_tient():
    guard = {"code": "g", "name": "Garde", "max_hp": 10**7, "attack": 1, "defense": 0}
    boss = mob(code="boss", max_hp=10_000, current_hp=1, attack=1, defense=0)
    res, index = assault([member(1, attack=400)], boss, guards=[guard],
                         passives={1: CombatPassives(splash_damage_pct=100)})
    assert res.victory and res.enemies[index]["defeated"] and not res.enemies[0]["defeated"]
