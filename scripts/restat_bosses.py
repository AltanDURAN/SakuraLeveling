"""Recalibre les world bosses sur la courbe de puissance RÉELLE des joueurs.

Constat mesuré (simulation avec le vrai moteur de combat, roster de prod) :
4 boss sur 5 étaient mathématiquement increvables — leur DÉFENSE dépassait
l'ATTAQUE des joueurs, donc chaque coup tombait au plancher de 1 dégât
(1 000 000 d'assauts pour le Dragon). C'est exactement l'invariant du projet :
« la DEF d'un monstre ne doit JAMAIS approcher l'ATK du joueur ».

Règles de calibrage (un boss = un palier de progression) :
  • ATK de référence du joueur ≈ 4 × niveau visé (mesuré : niv 31→133, niv 34→92) ;
  • DEF du boss = 35 % de l'ATK de l'équipe  → les coups portent vraiment ;
  • ATK du boss = 45 % de l'ATK de référence → mord fort sans balayer d'un coup ;
  • PV du boss  = dégâts d'un assaut × 6     → tombe vers le 6ᵉ jour du raid.

Usage : .venv/bin/python -m scripts.restat_bosses [--write]
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

CONTENT = Path(__file__).resolve().parents[1] / "app/infrastructure/content/boss_definitions.json"

# boss → niveau de joueur visé (palier de progression)
TARGET_LEVEL = {
    "slime_titan": 20,
    "gobelin_warlord": 40,
    "stone_colossus": 60,
    "shadow_wraith": 80,
    "ancient_dragon": 100,
}

from app.application.use_cases.world_boss import BOSS_FIGHT_MAX_TURNS

#: Capacités de chaque boss, exprimées en PROPORTIONS des joueurs de son
#: niveau (l'intention de design), converties en valeurs par `compute`.
#: Avant, c'étaient des valeurs fixes héritées de l'ancien modèle de stats
#: (V2, chiffres bien plus gros) : soin et immunité annulaient tout le raid.
#:   heal_share     : le boss regagne cette part des dégâts que le raid lui
#:                    inflige par tour (le raid doit donc taper plus fort) ;
#:   immunity_share : il ignore les coups inférieurs à cette part d'un coup
#:                    typique d'un joueur de son niveau (punit le sous-niveau) ;
#:   adds_share     : ses invocations frappent à cette part de son attaque.
MODIFIER_DESIGN: dict[str, dict[str, float]] = {
    "slime_titan": {"heal_share": 0.25, "immunity_share": 0.25},
    "gobelin_warlord": {"adds_share": 0.70},
    "stone_colossus": {"immunity_share": 0.50},
    "shadow_wraith": {},
    "ancient_dragon": {"heal_share": 0.20, "immunity_share": 0.50, "adds_share": 0.60},
}

PARTY_SIZE = 4                # taille d'équipe de référence
ASSAULTS_TO_KILL = 6          # le raid doit durer ~6 jours


def _reference_party(level: int, size: int = PARTY_SIZE) -> list[dict]:
    """Équipe de référence au niveau visé — définition partagée du joueur type,
    avec le bonus d'équipe RÉEL du raid (+5 % par participant en plus)."""
    from app.domain.services.reference_player import reference_stats
    from app.domain.services.world_boss_scaling_service import WorldBossScalingService

    stats = WorldBossScalingService().apply_team_bonus(reference_stats(level), size)
    return [
        {"player_id": i, "user_id": i, "name": f"ref{i}", "avatar_url": "",
         "stats": stats, "current_hp": stats.max_hp, "max_hp": stats.max_hp,
         "current_mana": stats.mana_max, "mana_max": stats.mana_max}
        for i in range(size)
    ]


def _measure_damage_per_assault(level: int, attack: int, defense: int, boss: dict) -> int:
    """Rejoue un assaut RÉEL (moteur de combat, escalade comprise) et mesure les
    dégâts NETS : soins du boss déduits, immunité, renvoi et invocations
    appliqués — exactement comme `LaunchPartyFightWorldBossUseCase`.

    Avant, la mesure se faisait contre un boss SANS ses capacités : le Titan
    (soin 50 PV/tour) ou le Dragon (immunité < 100) étaient bien plus durs que
    prévu, et le raid de la semaine devenait ingagnable."""
    from datetime import datetime, UTC

    from app.domain.entities.mob_definition import MobDefinition
    from app.domain.services.party_combat_service import PartyCombatService

    now = datetime.now(UTC)
    # Le boss d'un raid en cours est déjà entamé : ses soins ne sont jamais
    # plafonnés par ses PV max. On le simule donc à mi-vie d'une réserve énorme.
    reserve = 10 ** 9
    mob = MobDefinition(
        id=1, code="calib", name="calib", description="", image_name="", family="",
        max_hp=2 * reserve, current_hp=reserve, attack=attack, defense=defense,
        speed=int(boss.get("speed", 8)), crit_chance=int(boss.get("crit_chance", 0)),
        crit_damage=int(boss.get("crit_damage", 150)), dodge=int(boss.get("dodge", 0)),
        hp_regeneration=0, xp_reward=0, gold_reward=0, spawn_weight=1, loot_table=[],
        created_at=now, updated_at=now, element="",
    )
    mods = boss.get("modifiers") or {}
    totals, actions = [], []
    for seed in range(5):
        random.seed(seed)
        result = PartyCombatService().fight_party_vs_mob(
            _reference_party(level), mob, max_turns=BOSS_FIGHT_MAX_TURNS,
            damage_immunity_threshold=int(mods.get("damage_immunity_threshold", 0)),
            boss_heal_per_turn=int(mods.get("auto_heal_per_turn", 0)),
            boss_reflect_pct=int(mods.get("reflect_pct", 0)),
            boss_adds=mods.get("adds"),
        )
        totals.append(max(0, reserve - result.mob_remaining_hp))
        actions.append(result.turns)
    _LAST_ACTIONS[0] = sum(actions) / len(actions)
    return int(sum(totals) / len(totals))


#: Nombre moyen d'actions du dernier assaut mesuré (sert au soin par tour).
_LAST_ACTIONS = [1.0]


def _scaled_modifiers(boss: dict, level: int, attack: int, defense: int) -> dict:
    """Recalcule les capacités du boss à partir de `MODIFIER_DESIGN`."""
    from app.domain.services.reference_player import reference_stats
    from app.domain.services.world_boss_scaling_service import WorldBossScalingService

    mods = dict(boss.get("modifiers") or {})
    design = MODIFIER_DESIGN.get(boss.get("code", ""), {})
    player = WorldBossScalingService().apply_team_bonus(reference_stats(level), PARTY_SIZE)
    typical_hit = max(1, player.attack - defense)
    if "immunity_share" in design:
        mods["damage_immunity_threshold"] = max(1, round(typical_hit * design["immunity_share"]))
    if "adds_share" in design and isinstance(mods.get("adds"), dict):
        mods["adds"] = {**mods["adds"], "attack": max(1, round(attack * design["adds_share"]))}
    if "heal_share" in design:
        # Dégâts BRUTS du raid par tour du boss (sans soin), puis la part soignée.
        raw = _measure_damage_per_assault(
            level, attack, defense, {**boss, "modifiers": {**mods, "auto_heal_per_turn": 0}},
        )
        boss_speed = int(boss.get("speed", 8))
        party_speed = player.speed * PARTY_SIZE
        boss_turns = max(1.0, _LAST_ACTIONS[0] * boss_speed / (boss_speed + party_speed))
        mods["auto_heal_per_turn"] = max(1, round(design["heal_share"] * raw / boss_turns))
    return mods


def compute(level: int, boss: dict | None = None) -> dict:
    from app.domain.services.reference_player import reference_stats

    ref = reference_stats(level)
    ref_atk = ref.attack
    # DEF du boss : laisse passer ~65 % de l'attaque du joueur. Au-delà, les
    # coups tombent au plancher de 1 dégât et le raid devient increvable.
    defense = max(5, round(ref_atk * 0.35))
    # ATK du boss : doit DÉPASSER la défense du joueur, sinon c'est l'impasse
    # symétrique — le boss ne tue personne et le combat tourne jusqu'au tour
    # maximum. ⚠️ En saison 1 un build équilibré a ATK ≈ DEF (même coût par
    # point) : une attaque exprimée en fraction de l'ATK du joueur passerait
    # donc SOUS sa défense. On la calcule sur la défense et les PV.
    attack = max(10, round(ref.defense + 0.06 * ref.max_hp))
    boss = boss or {}
    modifiers = _scaled_modifiers(boss, level, attack, defense) if boss else {}
    measured = _measure_damage_per_assault(level, attack, defense, {**boss, "modifiers": modifiers})
    max_hp = max(1000, int(round(measured * ASSAULTS_TO_KILL / 1000.0) * 1000))
    return {"max_hp": max_hp, "attack": attack, "defense": defense,
            "ref_atk": ref_atk, "measured": measured, "modifiers": modifiers}


def main() -> None:
    write = "--write" in sys.argv
    data = json.loads(CONTENT.read_text(encoding="utf-8"))
    bosses = data if isinstance(data, list) else data.get("bosses", [])
    print(f"{'boss':<26}{'PV':>12}{'ATK':>7}{'DEF':>7}   (ATK joueur réf.)")
    for b in bosses:
        level = TARGET_LEVEL.get(b["code"])
        if level is None:
            continue
        c = compute(level, b)
        if c["measured"] <= 0:
            print(f"⚠️  {b['name']} : AUCUN dégât net mesuré — ses capacités "
                  f"(soin, immunité…) annulent l'équipe de référence. À revoir.")
        print(f"{b['name']:<26}{c['max_hp']:>12,}{c['attack']:>7}{c['defense']:>7}"
              f"   niv {level} · {c['measured']:,} dégâts/assaut mesurés"
              .replace(",", " "))
        b["max_hp"], b["attack"], b["defense"] = c["max_hp"], c["attack"], c["defense"]
        if c["modifiers"] != (b.get("modifiers") or {}):
            print(f"{'':26}capacités : {b.get('modifiers')} → {c['modifiers']}")
            b["modifiers"] = c["modifiers"]
    if write:
        CONTENT.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
        print("\n✅ boss_definitions.json mis à jour")
    else:
        print("\n(dry-run — relancer avec --write pour appliquer)")


if __name__ == "__main__":
    main()
