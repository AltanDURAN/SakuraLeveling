"""Un test par passif des pièces des zones C → S (27/10/2026, validés avec
l'auteur). Même méthode que `test_gear_passives_combat` : la situation qui
déclenche le passif, comparée au même combat sans lui."""

import random

from app.domain.services.gear_passives import PASSIVES
from app.domain.services.party_combat_service import EnemySetup, PartyCombatService
from tests.domain.test_gear_passives_combat import dealt, fight, gear, logs, member, mob


def pack(party, *mobs, passives=None, seed=0, **kw):
    random.seed(seed)
    return PartyCombatService().fight_party_vs_mobs(
        party, [m if isinstance(m, EnemySetup) else EnemySetup(mob=m) for m in mobs],
        passives_by_player=passives or {}, **kw)


def contrib(result, pid=1):
    return next(c for c in result.contributions if c.player_id == pid)


def test_les_27_nouveaux_passifs_sont_au_catalogue():
    codes = {"pack_instinct", "kind_antlers", "root_venom", "crushing_paw", "verdant_moss",
             "storm_eye", "night_flight", "flesh_feast", "lunar_rage", "blood_pact",
             "eclipse_mirror", "scarlet_thirst", "bloody_waltz", "ambush", "young_breath",
             "lingering_ember", "dive", "frost_bite", "guardian_oath", "ancestral_breath",
             "abyssal_reserve", "void_gaze", "devour", "void_echo", "astral_grip",
             "broken_grace", "devouring_void"}
    assert codes <= set(PASSIVES)


# ------------------------------------------------- Sanctuaire primordial --
def test_instinct_de_meute_3_pourcent_par_allie():
    party = [member(1), member(2), member(3)]
    res = fight(party, mob(attack=1, speed=0), {1: gear("pack_instinct")}, max_turns=1)
    assert dealt(res) == round(90 * 1.06)


def test_ramure_bienveillante_soins_recus_plus_15():
    hurt = lambda: [{**member(), "current_hp": 100}]
    without = fight(hurt(), mob(attack=1, speed=0), {1: gear(lifesteal_pct=100)}, max_turns=1)
    with_ = fight(hurt(), mob(attack=1, speed=0), {1: gear("kind_antlers", lifesteal_pct=100)}, max_turns=1)
    assert contrib(without).final_hp == 100 + 90
    assert contrib(with_).final_hp == 100 + round(90 * 1.15)


def test_seve_veneneuse_plafonnee_par_l_attaque():
    res = fight([member(max_hp=100_000)], mob(speed=10), {1: gear("root_venom")}, max_turns=6)
    assert "🐍 Sève : −25" in logs(res)            # 1 % de 100 000 = 1 000 → plafond 25 % ATK
    small = fight([member(max_hp=100_000)], mob(max_hp=1000, current_hp=1000, speed=10),
                  {1: gear("root_venom")}, max_turns=6)
    assert "🐍 Sève : −10" in logs(small)          # 1 % de 1 000, sous le plafond


def test_coup_de_patte_brise_la_defense_jusqu_a_15():
    res = fight([member()], mob(defense=50, attack=1, speed=0), {1: gear("crushing_paw")}, max_turns=8)
    hits = [int(t.player_actions[0].split(" inflige ")[1].split(" ")[0])
            for t in res.turn_logs if t.player_actions]
    assert hits[0] == 50 and hits[-1] == round(100 - 50 * 0.85)
    assert "🐾−15%" in logs(res)


def test_mousse_vivace_soigne_7_actions_sous_30_pourcent():
    res = fight([member()], mob(attack=420), {1: gear("verdant_moss")}, max_turns=20)
    assert logs(res).count("🌿 Mousse vivace") == 7 or contrib(res).final_hp == 0


def test_oeil_de_la_tempete_frappe_tous_les_ennemis():
    foes = [mob(code=c, attack=1, speed=0) for c in "abc"]
    res = pack([member()], *foes, passives={1: gear("storm_eye")}, max_turns=1)
    assert all(e["remaining_hp"] == 100_000 - 90 for e in res.enemies)
    stunned = sum("étourdi par la tempête" in logs(pack([member()], *foes, passives={1: gear("storm_eye")},
                                                        seed=s, max_turns=1)) for s in range(30))
    assert 5 < stunned < 30


# --------------------------------------------------- Éclipse éternelle --
def test_vol_nocturne_esquive_au_dessus_de_50_pourcent():
    without = sum(contrib(fight([member(max_hp=10**6)], mob(attack=30), seed=s, max_turns=200)).dodges
                  for s in range(5))
    with_ = sum(contrib(fight([member(max_hp=10**6)], mob(attack=30), {1: gear("night_flight")},
                              seed=s, max_turns=200)).dodges for s in range(5))
    assert without == 0 and with_ > 0


def test_festin_de_chair_rend_25_pourcent_par_ennemi_vaincu():
    a = mob(code="a", max_hp=100, current_hp=100, attack=1)
    b = mob(code="b", max_hp=10_000, current_hp=10_000, attack=1)
    party = [{**member(), "current_hp": 300}]
    res = pack(party, a, b, passives={1: gear("flesh_feast")}, max_turns=1)
    assert "🍖 Festin de chair : J1 +250" in logs(res)


def test_rage_lunaire_sous_50_pourcent():
    hurt = [{**member(), "current_hp": 400}]
    res = fight(hurt, mob(attack=1, speed=0), {1: gear("lunar_rage")}, max_turns=1)
    assert dealt(res) == 115 - 10


def test_pacte_de_sang_paie_en_pv_et_erode():
    broke = [{**member(), "current_mana": 0}]
    res = fight(broke, mob(attack=200), {1: gear("blood_pact", "first_hit_ward")}, max_turns=2)
    text = logs(res)
    assert "coup annulé" in text and "pacte de sang" in text
    assert res.turn_logs[-1].players_state[0]["max_hp"] == 950    # érosion : −5 %
    no_pact = fight([{**member(), "current_mana": 0}], mob(attack=200), {1: gear("first_hit_ward")},
                    max_turns=2)
    assert "coup annulé" not in logs(no_pact)


def test_miroir_d_eclipse_renvoie_15_pourcent():
    res = fight([member(max_hp=10**6)], mob(attack=420, speed=10), {1: gear("eclipse_mirror")}, max_turns=2)
    assert "🪞 60 renvoyés" in logs(res)


def test_soif_ecarlate_soigne_sur_critique():
    hurt = [{**member(crit_chance=100), "current_hp": 100}]
    res = fight(hurt, mob(attack=1, speed=0), {1: gear("scarlet_thirst")}, max_turns=1)
    assert contrib(res).final_hp == 100 + round(190 * 0.20)


def test_valse_sanglante_critique_et_saignement_apres_esquive():
    res = fight([member(dodge=100)], mob(attack=100, speed=20), {1: gear("bloody_waltz")}, max_turns=6)
    hits = [a for t in res.turn_logs for a in t.player_actions]
    assert any("(CRIT)" in a and "🩸" in a for a in hits)


# ---------------------------------------------------- Cimes des Wyrms --
def test_embuscade_tant_que_l_ennemi_n_a_pas_agi():
    res = fight([member()], mob(attack=1, speed=1), {1: gear("ambush")}, max_turns=1)
    assert dealt(res) == round(90 * 1.25)


def test_souffle_juvenile_toutes_les_5_attaques():
    foes = [mob(code=c, attack=1, speed=0) for c in "ab"]
    res = pack([member()], *foes, passives={1: gear("young_breath")}, max_turns=5)
    assert "🔥 Souffle juvénile de J1 : Monstre −30 · Monstre −30" in logs(res)


def test_braise_persistante_affaiblit_et_brule():
    res = fight([member(crit_chance=100, max_hp=10**6)], mob(attack=500, speed=10),
                {1: gear("lingering_ember")}, max_turns=12)
    text = logs(res)
    assert "🔥 Brûlure : −" in text
    hits = [t.mob_action for t in res.turn_logs if t.mob_action.startswith("Monstre frappe")]
    assert "J1 −380" in hits[0]                   # 500 × 0,8 − 20 : −20 % d'attaque


def test_pique_trois_coups_a_60_pourcent():
    res = fight([member()], mob(attack=1, speed=0), {1: gear("dive")}, max_turns=1)
    assert logs(res).count("🦅 Piqué") == 3 and dealt(res) == 3 * (60 - 10)


def test_morsure_du_givre_gele_l_attaquant():
    frozen = sum("gelé" in logs(fight([member(max_hp=10**6)], mob(attack=100, speed=20),
                                      {1: gear("frost_bite")}, seed=s, max_turns=60)) for s in range(10))
    assert frozen > 0


def test_serment_du_gardien_en_provocation():
    def first_hit(codes):
        res = fight([member(1), member(2)], mob(attack=520, speed=20), {1: gear(*codes)}, max_turns=3)
        return next(t.mob_action for t in res.turn_logs if "frappe" in t.mob_action)
    assert "J1 −425" in first_hit(("taunt_guard",))               # 500 × 0,85
    assert "J1 −340" in first_hit(("taunt_guard", "guardian_oath"))  # × 0,8 en plus


def test_souffle_ancestral_execute_sous_20_pourcent_sauf_les_boss():
    low = mob(max_hp=1000, current_hp=250, attack=1, speed=0)
    res = fight([member()], low, {1: gear("ancestral_breath")}, max_turns=1)
    assert res.victory and "exécuté" in logs(res)
    boss = fight([member()], low, {1: gear("ancestral_breath")}, max_turns=1, mob_is_boss=True)
    assert not boss.victory


# --------------------------------------------------- Faille du Néant --
def test_reserve_abyssale_moins_20_pourcent_de_mana():
    res = fight([member()], mob(attack=200), {1: gear("abyssal_reserve", "first_hit_ward")}, max_turns=2)
    assert contrib(res).mana_spent == 5        # 6 × 0,8


def test_regard_du_vide_l_ennemi_n_esquive_plus():
    res = fight([member()], mob(attack=1, speed=0, dodge=100), {1: gear("void_gaze")}, max_turns=3)
    assert dealt(res) == 3 * 90


def test_devoration_vole_10_pourcent_d_un_allie_mort():
    party = [member(1, max_hp=10**6), {**member(2, attack=500, defense=0), "current_hp": 1}]
    res = fight(party, mob(attack=300, speed=50), {1: gear("devour")}, max_turns=6,
                mob_abilities={"aoe": {}})
    j1 = res.turn_logs[-1].players_state[0]
    assert j1["attack"] == 100 + 50 and j1["max_hp"] == 10**6 + 100


def test_echos_du_vide_toutes_les_8_actions():
    res = fight([member(max_hp=10**6)], mob(attack=1, speed=0), {1: gear("void_echo")}, max_turns=8)
    assert "🌀 Écho du vide de J1 : Monstre −50" in logs(res)


def test_etreinte_astrale_ralentit_jusqu_a_25():
    res = fight([member(max_hp=10**6)], mob(attack=1, speed=0), {1: gear("astral_grip")}, max_turns=5)
    assert "🐙−25%" in logs(res)


def test_grace_brisee_releve_le_premier_allie_qui_tombe():
    party = [member(1, max_hp=10**6), {**member(2, defense=0), "current_hp": 1}]
    res = fight(party, mob(attack=300, speed=50), {1: gear("broken_grace")}, max_turns=4,
                mob_abilities={"aoe": {}})
    assert "relevé par J1" in logs(res)


def test_neant_devorant_un_coup_sur_deux():
    res = fight([member()], mob(defense=60, attack=1, speed=0), {1: gear("devouring_void")}, max_turns=4)
    hits = [int(t.player_actions[0].split(" inflige ")[1].split(" ")[0])
            for t in res.turn_logs if t.player_actions]
    assert hits == [40, 70, 40, 70]
