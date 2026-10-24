"""Capacités des monstres des zones C → S : poison, brise-armure, régénération,
renvoi de dégâts, invocation."""

import random
from datetime import UTC, datetime

from app.domain.entities.mob_definition import MobDefinition
from app.domain.services.party_combat_service import PartyCombatService
from app.domain.value_objects.stats import Stats


def _mob(*, hp=100_000, attack=60, defense=0, speed=10):
    now = datetime.now(UTC)
    return MobDefinition(
        id=1, code="m", name="Mob", description="", image_name=None, family="x",
        max_hp=hp, current_hp=hp, attack=attack, defense=defense, speed=speed,
        crit_chance=0, crit_damage=100, dodge=0, hp_regeneration=0,
        xp_reward=1, gold_reward=1, spawn_weight=1, loot_table=None,
        created_at=now, updated_at=now,
    )


def _player(pid=1, *, hp=10_000, attack=50, defense=20, speed=10):
    return {
        "player_id": pid, "user_id": pid, "name": f"P{pid}", "avatar_url": None,
        "current_hp": hp, "max_hp": hp,
        "stats": Stats(max_hp=hp, attack=attack, defense=defense, speed=speed,
                       crit_chance=0, crit_damage=150, dodge=0, hp_regeneration=0),
    }


def fight(abilities, mob=None, party=None, turns=12, seed=0):
    random.seed(seed)
    return PartyCombatService().fight_party_vs_mob(
        party=party or [_player()], mob=mob or _mob(), mob_abilities=abilities,
        max_turns=turns)


def logs(r) -> str:
    return "\n".join(f"{t.mob_action} {' '.join(t.player_actions)}" for t in r.turn_logs)


def tanked(r, pid=1) -> int:
    c = next(c for c in r.contributions if c.player_id == pid)
    return c.max_hp - c.final_hp


def test_poison_ronge_un_pourcentage_des_pv_max():
    r = fight({"poison": {"pct_max_hp": 2, "turns": 4}})
    assert "☠️ Poison : P1 −200" in logs(r)        # 2 % de 10 000 PV
    assert tanked(r) > tanked(fight({}))


def test_poison_non_cumulable():
    text = logs(fight({"poison": {"pct_max_hp": 2, "turns": 4}}, turns=30))
    assert "−400" not in text.split("☠️ Poison")[-1].split("\n")[0]


def test_brise_armure_plafonne():
    r = fight({"armor_break": {"pct": 10, "max_pct": 30}}, turns=30)
    hits = [int(x.split("−")[1].split()[0]) for t in r.turn_logs
            for x in t.mob_action.split(" · ") if "frappe" in t.mob_action and "−" in x]
    # 60 ATK − 20 DEF = 40, puis DEF −10 % par coup jusqu'à −30 % (14 DEF → 46).
    assert hits[0] == 40 and hits[1] == 42 and max(hits) == 46


def test_regeneration_du_monstre():
    mob = _mob(hp=1000, attack=1)
    plain = fight({}, mob=mob, turns=10)
    regen = fight({"regen": {"pct": 3}}, mob=_mob(hp=1000, attack=1), turns=10)
    assert regen.mob_remaining_hp > plain.mob_remaining_hp


def test_renvoi_de_degats():
    r = fight({"reflect": {"pct": 20}}, mob=_mob(attack=1), turns=4)
    assert "(renvoi 10)" in logs(r)               # 20 % de 50 dégâts


def test_invocations():
    with_adds = fight({"summon": {"atk_pct": 50, "every": 1, "max": 2}}, turns=20)
    assert tanked(with_adds) > tanked(fight({}, turns=20))
