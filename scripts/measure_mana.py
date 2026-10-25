"""Mesure le coût en mana des compétences actives (`combat_passives.MANA_COSTS`)
avec le vrai moteur et les builds de rôle (`reference_roles`).

Trois questions, dans l'ordre où le calibrage du 25/10/2026 les a tranchées :
  1. que rapporte UN déclenchement de chaque compétence (combats d'élite,
     sans limite de mana) ? → les prix relatifs ;
  2. quelle part de sa réserve un rôle vide-t-il dans un combat d'élite, et
     l'élite reste-t-elle gagnée ? → le budget (l'ancre, le sort de soin) ;
  3. le farm reste-t-il gratuit, et que se passe-t-il quand on enchaîne ?

Usage : .venv/bin/python -m scripts.measure_mana
(à relancer après un changement des coûts, du moteur, de l'arbre ou des élites)
"""

from __future__ import annotations

import json
import random
import re
import statistics
from collections import defaultdict
from pathlib import Path

from app.domain.services.combat_passives import MANA_COSTS
from app.domain.services.mob_ability_service import GROUP_ELITES, get_mob_abilities
from app.domain.services.party_combat_service import PartyCombatService
from scripts import reference_roles as R
from scripts.restat_mobs import ASSIGN, as_mob, restat

MOBS = {m["code"]: m for m in json.loads(
    (Path(__file__).resolve().parents[1] / "app/infrastructure/content/mobs.json").read_text(encoding="utf-8"))}
ROLES = ("dps", "tank", "support")
#: Minutes entre deux combats de farm (simulateur de saison : 3 min par combat).
MINUTES_PER_FIGHT = 3

#: Ce que rapporte un déclenchement, lu dans le journal du combat.
_VALUE = {
    "heal_spell": re.compile(r"💚 \S+ (?:se soigne|soigne \S+) : \+(\d+) PV"),
    "ally_heal": re.compile(r"✚ \S+ \+(\d+)"),
    "lifesteal": re.compile(r"🧛 \+(\d+)"),
    "redirect": re.compile(r"🧱 \S+ encaisse (\d+)"),
    "counter_attack": re.compile(r"↩️ Riposte — \S+ inflige (\d+) dégâts"),
    "double_strike": re.compile(r"⚡ Coup double — \S+ inflige (\d+) dégâts"),
}


def elite_mob(code: str):
    m = MOBS[code]
    return as_mob(code, {k: m.get(k, d) for k, d in (
        ("max_hp", 0), ("attack", 0), ("defense", 0), ("speed", 5),
        ("crit_chance", 0), ("crit_damage", 100), ("dodge", 0))})


def fights(compo: str, level: int, mob, abilities: dict, costs, gaps=(), n=20):
    """Combats enchaînés (PV pleins, mana reporté + `gap` minutes de régén) :
    ([victoires par combat], [[mana dépensé par membre] par combat], résultats du 1er)."""
    wins = [0] * (len(gaps) + 1)
    spend = [[0.0] * len(compo) for _ in range(len(gaps) + 1)]
    firsts = []
    for seed in range(n):
        random.seed(seed)
        members, passives, tactics = R.party(compo, level)
        mana = {m["player_id"]: m["mana_max"] for m in members}
        for k in range(len(gaps) + 1):
            for m in members:
                m["current_mana"] = mana[m["player_id"]]
            res = PartyCombatService().fight_party_vs_mob(
                members, mob, mob_abilities=abilities, passives_by_player=passives,
                tactics_by_player=tactics, mana_costs=costs)
            if k == 0:
                firsts.append(res)
            wins[k] += res.victory
            for c in res.contributions:
                spend[k][c.player_id - 1] += c.mana_spent / n
                if k < len(gaps):
                    regen = members[c.player_id - 1]["stats"].mana_regeneration * gaps[k]
                    mana[c.player_id] = min(c.mana_max, c.final_mana + regen)
    return [w / n for w in wins], spend, firsts


def values() -> None:
    print("1. Valeur d'un déclenchement (élites, sans limite de mana)")
    found, ratios = defaultdict(list), []
    for code in sorted(GROUP_ELITES, key=lambda c: ASSIGN[c][0]):
        level = ASSIGN[code][0]
        _, _, results = fights("DTS", level, elite_mob(code), get_mob_abilities(code), {})
        for res in results:
            text = "\n".join(f"{t.mob_action} {' '.join(t.player_actions)}" for t in res.turn_logs)
            for ability, pattern in _VALUE.items():
                found[ability] += [int(x) for x in pattern.findall(text)]
            dealt = sum(c.damage_dealt for c in res.contributions)
            taken = sum(c.max_hp - c.final_hp + c.hp_healed for c in res.contributions)
            ratios.append(taken / max(1, dealt))
    rate = statistics.median(ratios)
    heal = statistics.mean(found["heal_spell"]) if found["heal_spell"] else 1
    print(f"   (un dégât infligé vaut ~{rate:.2f} PV : PV perdus + soignés par dégât)")
    for ability, amounts in found.items():
        if not amounts:
            continue
        hp = statistics.mean(amounts) * (rate if ability in ("counter_attack", "double_strike") else 1)
        print(f"   {ability:15s} {len(amounts):5d} fois · {statistics.mean(amounts):6.0f} → "
              f"{hp / heal:4.2f} soin · coût {MANA_COSTS[ability]} ({MANA_COSTS[ability] / MANA_COSTS['heal_spell']:.2f} soin)")


def budget() -> None:
    print("\n2. Élites : victoires (réserve pleine / +3 min / +10 min) · % de réserve dépensé (D, T, S)")
    for code in sorted(GROUP_ELITES, key=lambda c: ASSIGN[c][0]):
        level = ASSIGN[code][0]
        wins, spend, _ = fights("DTS", level, elite_mob(code), get_mob_abilities(code), None, gaps=(3, 10))
        pools = [R.build(r, level).stats.mana_max for r in ROLES]
        pct = [round(100 * s / p) for s, p in zip(spend[0], pools)]
        print(f"   {code:18s} niv {level:3d} : {wins[0]:4.0%} {wins[1]:4.0%} {wins[2]:4.0%} · {pct}")


def farm() -> None:
    print(f"\n3. Farm : mana dépensé par combat et par joueur / régénéré en {MINUTES_PER_FIGHT} min")
    for level in (30, 60, 100):
        mob = as_mob("standard", restat(level, "standard"))
        cells = []
        for compo in ("D", "T", "S", "G", "DTS", "GGG"):
            _, spend, _ = fights(compo, level, mob, {}, None, n=10)
            regen = min(R.build(R.ROLE_OF[c], level).stats.mana_regeneration for c in compo)
            cells.append(f"{compo} {max(spend[0]):.0f}/{regen * MINUTES_PER_FIGHT}")
        print(f"   niv {level:3d} : " + " · ".join(cells))


if __name__ == "__main__":
    values()
    budget()
    farm()
