"""Un test par passif d'équipement (moteur de combat de groupe et duel).

Chaque test met en place la situation qui déclenche le passif, puis compare au
même combat sans lui. Les tirages aléatoires sont neutralisés (crit/esquive à
0 % ou 100 %) ou mesurés statistiquement.
"""

import random
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from app.domain.entities.mob_definition import MobDefinition
from app.domain.services.combat_passives import CombatPassives
from app.domain.services.duel_combat_service import DuelCombatService
from app.domain.services.party_combat_service import PartyCombatService
from app.domain.value_objects.stats import Stats

NOW = datetime.now(UTC)


def stats(**kw) -> Stats:
    base = dict(max_hp=1000, attack=100, defense=20, speed=10, crit_chance=0,
                crit_damage=200, dodge=0, hp_regeneration=0, mana_max=0, mana_regeneration=0)
    base.update(kw)
    return Stats(**base)


def mob(**kw) -> MobDefinition:
    base = dict(id=1, code="m", name="Monstre", description="", image_name="", family="",
                max_hp=100_000, current_hp=100_000, attack=80, defense=10, speed=10,
                crit_chance=0, crit_damage=150, dodge=0, hp_regeneration=0,
                xp_reward=0, gold_reward=0, spawn_weight=1, loot_table=[],
                created_at=NOW, updated_at=NOW, element="")
    base.update(kw)
    return MobDefinition(**base)


def member(pid=1, **kw):
    st = stats(**kw)
    return {"player_id": pid, "user_id": pid, "name": f"J{pid}", "avatar_url": "",
            "stats": st, "current_hp": st.max_hp, "max_hp": st.max_hp,
            "current_mana": 0, "mana_max": 0}


def gear(*codes, **kw) -> CombatPassives:
    return CombatPassives(gear=frozenset(codes), **kw)


def fight(party, m, passives=None, **kw):
    random.seed(kw.pop("seed", 0))
    return PartyCombatService().fight_party_vs_mob(
        party, m, passives_by_player=passives or {}, **kw)


def dealt(result, pid=1) -> int:
    return next(c.damage_dealt for c in result.contributions if c.player_id == pid)


def tanked_hp(result, pid=1) -> int:
    c = next(c for c in result.contributions if c.player_id == pid)
    return c.max_hp - c.final_hp


def logs(result) -> str:
    return "\n".join(f"{t.mob_action} {' '.join(t.player_actions)}" for t in result.turn_logs)


# ------------------------------------------------------------- offensifs --
def test_frappe_d_ouverture_premiere_attaque_critique():
    without = fight([member()], mob(), max_turns=1)
    with_ = fight([member()], mob(), {1: gear("first_strike_crit")}, max_turns=1)
    assert dealt(without) == 100 - 10
    assert dealt(with_) == 200 - 10           # critique forcé (×2)
    assert "(CRIT)" in logs(with_)


def test_frappe_d_ouverture_super_critique():
    res = fight([member(crit_chance=100)], mob(), {1: gear("first_strike_crit")}, max_turns=1)
    assert dealt(res) == 400 - 10             # ×2 ×2 : les deux critiques se cumulent


def test_perce_armure_ignore_quinze_pour_cent_de_defense():
    from app.application.services.combat_passives_resolver import with_gear_passives

    class Item:
        rarity = "epic"
        item_definition = type("D", (), {"passive": "armor_pierce"})()

    merged = with_gear_passives(CombatPassives(), [Item()])
    assert merged.armor_penetration_pct == 15 and merged.has("armor_pierce")
    res = fight([member()], mob(defense=60), {1: merged}, max_turns=1)
    assert dealt(res) == 100 - 51


def test_executeur_sous_cinquante_pour_cent():
    m = mob(max_hp=100_000, current_hp=40_000)
    assert dealt(fight([member()], m, {1: gear("executioner")}, max_turns=1)) == round(90 * 1.2)
    healthy = mob()
    assert dealt(fight([member()], healthy, {1: gear("executioner")}, max_turns=1)) == 90


def test_tueur_de_boss():
    p = {1: gear("boss_slayer")}
    assert dealt(fight([member()], mob(), p, max_turns=1, mob_is_boss=True)) == round(90 * 1.15)
    assert dealt(fight([member()], mob(), p, max_turns=1)) == 90


def test_fureur_montante_plafonnee():
    res = fight([member(speed=1000)], mob(speed=1), {1: gear("rising_fury")}, max_turns=30)
    hits = [int(a.split("inflige ")[1].split()[0]) for t in res.turn_logs
            for a in t.player_actions if "inflige" in a]
    assert hits[0] == 90 and hits[1] == 91           # +1 % d'ATK
    assert max(hits) == 120 - 10                      # plafond +20 %


def test_puissance_elementaire():
    p = {1: gear("elemental_power")}
    base = dealt(fight([member()], mob(), {1: gear()}, max_turns=1,
                       elemental_mult_by_player={1: 1.3}))
    boosted = dealt(fight([member()], mob(), p, max_turns=1, elemental_mult_by_player={1: 1.3}))
    assert boosted == round(base * 1.10)


def test_coup_double_environ_dix_pour_cent():
    procs = attacks = 0
    for seed in range(200):
        res = fight([member()], mob(), {1: gear("double_strike")}, max_turns=40, seed=seed)
        text = logs(res)
        procs += text.count("Coup double")
        attacks += text.count("inflige") - text.count("Coup double")
    assert 0.06 < procs / attacks < 0.14


# ------------------------------------------------------------- défensifs --
def test_garde_de_l_exil_annule_la_premiere_attaque():
    res = fight([member(speed=1)], mob(speed=100), {1: gear("first_hit_ward")}, max_turns=2)
    assert "coup annulé" in logs(res)
    plain = fight([member(speed=1)], mob(speed=100), max_turns=2)
    assert tanked_hp(res) < tanked_hp(plain)


def test_bandelettes_reduisent_les_critiques_recus():
    m = mob(crit_chance=100, crit_damage=200, speed=100)
    with_ = fight([member(speed=1)], m, {1: gear("crit_ward")}, max_turns=1)
    without = fight([member(speed=1)], m, max_turns=1)
    assert tanked_hp(with_) == round(tanked_hp(without) * 0.75)


def test_peau_de_pierre_fait_monter_la_defense():
    res = fight([member(speed=1, defense=100, max_hp=100_000)], mob(speed=100, attack=300),
                {1: gear("stone_skin")}, max_turns=40)
    hits = [int(x.split("−")[1].split()[0]) for t in res.turn_logs
            for x in t.mob_action.split(" · ") if "−" in x]
    assert hits[0] == 200 and hits[1] == 199 and min(hits) == 300 - 120   # DEF +20 % max


def test_epines_augmentent_le_contrecoup_de_dix_pour_cent():
    # DEF 325 contre ATK 300 : 325 − 75 % × 300 = 100 de contrecoup, 110 avec Épines.
    plain = fight([member(speed=1, defense=325)], mob(speed=100, attack=300), max_turns=3)
    assert "🔁 100 en contrecoup" in logs(plain)
    res = fight([member(speed=1, defense=325)], mob(speed=100, attack=300),
                {1: gear("thorns")}, max_turns=3)
    assert "🔁 110 en contrecoup" in logs(res) and dealt(res) >= 110


def test_riposte_environ_dix_pour_cent():
    procs = hits = 0
    for seed in range(200):
        res = fight([member(speed=1, max_hp=100_000)], mob(speed=100),
                    {1: gear("counter_attack")}, max_turns=40, seed=seed)
        text = logs(res)
        procs += text.count("Riposte")
        hits += text.count(" frappe : ")
    assert 0.06 < procs / hits < 0.14


def test_revenant_revient_a_cinquante_pour_cent_une_fois():
    res = fight([member(speed=1, max_hp=200, defense=0)], mob(speed=100, attack=150),
                {1: gear("undying")}, max_turns=20)
    assert logs(res).count("revient à la vie") == 1


def test_tenacite_partage_le_drapeau_de_tenace():
    from app.application.services.combat_passives_resolver import with_gear_passives

    class Item:
        rarity = "legendary"
        item_definition = type("D", (), {"passive": "tenacity"})()

    assert with_gear_passives(CombatPassives(), [Item()]).last_stand


def test_pare_souffle_divise_les_degats_de_zone():
    party = [member(1, speed=1), member(2, speed=1)]
    m = mob(speed=100)
    with_ = fight(party, m, {1: gear("blast_ward")}, max_turns=1, mob_abilities={"aoe": {}})
    without = fight(party, m, max_turns=1, mob_abilities={"aoe": {}})
    assert tanked_hp(with_, 1) == round(tanked_hp(without, 1) * 0.5)
    assert tanked_hp(with_, 2) == tanked_hp(without, 2)


def test_pas_de_l_ombre_apres_une_esquive():
    svc = PartyCombatService()
    svc._passives = {1: gear("shadow_step")}
    svc._party = []
    target = {"player_id": 1, "stats": stats(dodge=100), "hp": 1000, "max_hp": 1000, "shield": 0}
    contributions = {1: type("C", (), {"dodges": 0, "damage_tanked": 0})()}
    _, _, dodged = svc._resolve_mob_hit(mob(), target, contributions, {}, {}, "")
    assert dodged and target["shadow"] and target["shadow_guard"]


def test_defi_commence_en_provocation_avec_moins_quinze_pour_cent():
    party = [member(1, speed=1), member(2, speed=1)]
    res = fight(party, mob(speed=100), {2: gear("taunt_guard")}, max_turns=1)
    assert tanked_hp(res, 2) == round((80 - 20) * 0.85) and tanked_hp(res, 1) == 0


def test_volonte_de_fer_immunise_au_charme():
    party = [member(1, attack=500), member(2)]
    charmed = fight(party, mob(), max_turns=2, mob_abilities={"charm": {}})
    assert "charme J1" in logs(charmed)
    immune = fight(party, mob(), {1: gear("iron_will")}, max_turns=2, mob_abilities={"charm": {}})
    assert "charme J1" not in logs(immune) and "charme J2" in logs(immune)


# ------------------------------------------------------ effets sur l'ennemi --
def test_cri_affaiblissant_non_cumulable():
    party = [member(1, speed=1), member(2, speed=1)]
    one = fight(party, mob(speed=100, attack=220), {1: gear("weakening_cry")}, max_turns=1)
    two = fight(party, mob(speed=100, attack=220),
                {1: gear("weakening_cry"), 2: gear("weakening_cry")}, max_turns=1)
    assert tanked_hp(one, 1) + tanked_hp(one, 2) == 209 - 20
    assert tanked_hp(two, 1) + tanked_hp(two, 2) == 209 - 20   # pas −10 %


def test_anti_soin_divise_le_soin_du_chaman():
    m = mob(max_hp=1000, current_hp=1000, speed=10)
    res = fight([member(attack=400, speed=10)], m, {1: gear("anti_heal")}, max_turns=4,
                mob_abilities={"heal_once_below": {"hp_pct": 50}})
    assert "entravé" in logs(res)


def test_mains_guerisseuses_frappent_l_ennemi():
    healer = gear("healing_hands", healer=True)
    party = [member(1, attack=100, speed=10), member(2, speed=1)]
    party[1]["current_hp"] = 100
    res = fight(party, mob(speed=1), {1: healer}, max_turns=1)
    # Soin de base 50 % de l'ATK, +10 % ⇒ 55 PV ; 10 % frappent le monstre.
    assert dealt(res, 1) == round(55 * 0.10)


# ---------------------------------------------------------------- duels --
def duel(a_codes=(), b_codes=(), seed=0, **b_stats):
    random.seed(seed)
    return DuelCombatService().fight_player_vs_player(
        stats(), stats(**b_stats), a_passives=gear(*a_codes), b_passives=gear(*b_codes))


def test_duel_frappe_d_ouverture():
    first = duel(("first_strike_crit",)).turn_logs[0]
    assert first.actor == "a" and first.is_crit and first.damage == 200 - 20


def test_duel_garde_de_l_exil():
    assert duel(b_codes=("first_hit_ward",)).turn_logs[0].damage == 0


def test_duel_revenant():
    res = duel(b_codes=("undying",), max_hp=150)
    assert res.turns > duel(max_hp=150).turns
