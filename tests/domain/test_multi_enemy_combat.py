"""Combats contre plusieurs ennemis (27/10/2026) : la tour et les meutes.

Un combat à un seul ennemi est un groupe réduit à un : `fight_party_vs_mob`
doit rendre EXACTEMENT le même combat qu'avant (même tirage, même issue)."""

import random

from app.domain.services.party_combat_service import EnemySetup, PartyCombatService
from tests.domain.test_gear_passives_combat import CombatPassives, dealt, member, mob


def pack(party, *mobs, passives=None, seed=0, **kw):
    random.seed(seed)
    return PartyCombatService().fight_party_vs_mobs(
        party, [m if isinstance(m, EnemySetup) else EnemySetup(mob=m) for m in mobs],
        passives_by_player=passives or {}, **kw)


def test_un_seul_ennemi_rend_le_meme_combat():
    m = mob(max_hp=3000, current_hp=3000, attack=150, crit_chance=20, dodge=5)
    random.seed(7)
    single = PartyCombatService().fight_party_vs_mob([member(), member(2)], m)
    multi = pack([member(), member(2)], m, seed=7)
    assert single.victory == multi.victory and single.turns == multi.turns
    assert [c.damage_dealt for c in single.contributions] == [c.damage_dealt for c in multi.contributions]
    assert multi.mob_remaining_hp == single.mob_remaining_hp
    assert multi.enemies == [{"code": "m", "name": "Monstre", "max_hp": 3000,
                              "remaining_hp": multi.mob_remaining_hp, "defeated": multi.victory}]


def test_la_victoire_exige_tous_les_ennemis_et_cumule_les_recompenses():
    a = mob(code="a", name="Loup", max_hp=500, current_hp=500, attack=50, xp_reward=10, gold_reward=5)
    b = mob(code="b", name="Ours", max_hp=800, current_hp=800, attack=50, xp_reward=20, gold_reward=7)
    res = pack([member()], a, b)
    assert res.victory and all(e["defeated"] for e in res.enemies)
    assert (res.xp_gained, res.gold_gained) == (30, 12)
    assert res.mob_name == "Loup et Ours"
    assert res.turn_logs[0].enemies_state and len(res.turn_logs[0].enemies_state) == 2


def test_les_joueurs_frappent_l_ennemi_le_plus_abime():
    healthy = mob(code="a", name="Intact", max_hp=10_000, current_hp=10_000, attack=1, speed=0)
    hurt = mob(code="b", name="Blessé", max_hp=10_000, current_hp=2_000, attack=1, speed=0)
    res = pack([member()], healthy, hurt, max_turns=3)
    intact, blesse = res.enemies
    assert intact["remaining_hp"] == 10_000 and blesse["remaining_hp"] < 2_000


def test_chaque_ennemi_agit():
    one = pack([member(max_hp=100_000)], mob(attack=200), max_ticks=200)
    three = pack([member(max_hp=100_000)], mob(code="a", attack=200), mob(code="b", attack=200),
                 mob(code="c", attack=200), max_ticks=200)
    taken = lambda r: r.contributions[0].damage_tanked
    assert taken(three) == 3 * taken(one)       # même durée, trois fois plus de coups


def test_aoe_touche_les_voisins_de_la_cible():
    enemies = [mob(code=c, name=c, max_hp=10_000, current_hp=10_000, attack=1, speed=0) for c in "abcd"]
    res = pack([member()], *enemies, passives={1: CombatPassives(splash_damage_pct=25)}, max_turns=1)
    hp = [e["remaining_hp"] for e in res.enemies]
    assert hp[0] == 10_000 - 90                       # la cible (première de la formation)
    assert hp[1] == 10_000 - round(90 * 0.25)         # son voisin
    assert hp[2] == hp[3] == 10_000                   # trop loin
    assert dealt(res) == 90 + round(90 * 0.25)


def test_une_provocation_vaut_pour_le_prochain_coup_de_chaque_ennemi():
    tank, dps = member(1, max_hp=100_000), member(2, max_hp=100_000, defense=0)
    foes = [mob(code=c, attack=300, speed=10) for c in "ab"]
    res = pack([tank, dps], *foes, passives={1: CombatPassives(gear=frozenset({"taunt_guard"}))},
               max_turns=4)
    first_hits = [t.mob_action for t in res.turn_logs if "frappe" in t.mob_action][:2]
    assert all("J1" in line for line in first_hits)


def test_le_slime_relache_ceux_qu_il_a_engloutis_en_mourant():
    slime = EnemySetup(mob=mob(code="slime", name="Slime", max_hp=300, current_hp=300, attack=1),
                       abilities={"absorb": {"chance": 100, "stat_pct": 0}})
    other = mob(code="b", name="Autre", max_hp=5_000, current_hp=5_000, attack=1)
    strong, weak = member(1, attack=500), member(2, attack=100)
    res = pack([strong, weak], slime, other)
    assert res.victory
    assert dealt(res, 2) > 0          # libéré à la mort du slime, il a pu frapper l'autre
