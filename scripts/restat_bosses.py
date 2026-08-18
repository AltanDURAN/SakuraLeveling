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
import sys
from pathlib import Path

CONTENT = Path(__file__).resolve().parents[1] / "app/infrastructure/content/boss_definitions.json"

# boss → niveau de joueur visé (palier de progression)
TARGET_LEVEL = {
    "slime_titan": 35,
    "gobelin_warlord": 50,
    "stone_colossus": 70,
    "shadow_wraith": 85,
    "ancient_dragon": 100,
}
PLAYER_ATK_PER_LEVEL = 4      # mesuré sur les joueurs réels (niv 31 → ATK 133)
PARTY_SIZE = 4                # taille d'équipe de référence
ASSAULTS_TO_KILL = 6          # le raid doit durer ~6 jours


def _reference_party(level: int, size: int = PARTY_SIZE) -> list[dict]:
    """Équipe de référence au niveau visé, avec les stats du VO canonique."""
    from app.domain.value_objects.stats import Stats

    atk = PLAYER_ATK_PER_LEVEL * level
    stats = Stats(max_hp=100 + level * 12, attack=atk, defense=level,
                  speed=5 + level // 10, crit_chance=15, crit_damage=150,
                  dodge=5, hp_regeneration=0, mana_max=100, mana_regeneration=0)
    return [
        {"player_id": i, "user_id": i, "name": f"ref{i}", "avatar_url": "",
         "stats": stats, "current_hp": stats.max_hp, "max_hp": stats.max_hp,
         "current_mana": stats.mana_max, "mana_max": stats.mana_max}
        for i in range(size)
    ]


def _measure_damage_per_assault(level: int, attack: int, defense: int) -> int:
    """Simule un assaut réel avec le moteur de combat pour MESURER les dégâts,
    au lieu de les estimer avec une constante devinée."""
    from datetime import datetime, UTC

    from app.domain.entities.mob_definition import MobDefinition
    from app.domain.services.party_combat_service import PartyCombatService

    now = datetime.now(UTC)
    dummy_hp = 10 ** 9  # assez gros pour que le boss ne meure pas pendant la mesure
    mob = MobDefinition(
        id=1, code="calib", name="calib", description="", image_name="", family="",
        max_hp=dummy_hp, current_hp=dummy_hp, attack=attack, defense=defense,
        speed=12, crit_chance=10, crit_damage=150, dodge=0, hp_regeneration=0,
        xp_reward=0, gold_reward=0, spawn_weight=1, loot_table=[],
        created_at=now, updated_at=now, element="",
    )
    result = PartyCombatService().fight_party_vs_mob(
        _reference_party(level), mob, max_turns=4000,
    )
    return sum(c.damage_dealt for c in result.contributions)


def compute(level: int) -> dict:
    ref_atk = PLAYER_ATK_PER_LEVEL * level
    defense = max(5, round(ref_atk * 0.35))
    attack = max(10, round(ref_atk * 0.45))
    measured = _measure_damage_per_assault(level, attack, defense)
    max_hp = max(1000, int(round(measured * ASSAULTS_TO_KILL / 1000.0) * 1000))
    return {"max_hp": max_hp, "attack": attack, "defense": defense,
            "ref_atk": ref_atk, "measured": measured}


def main() -> None:
    write = "--write" in sys.argv
    data = json.loads(CONTENT.read_text(encoding="utf-8"))
    bosses = data if isinstance(data, list) else data.get("bosses", [])
    print(f"{'boss':<26}{'PV':>12}{'ATK':>7}{'DEF':>7}   (ATK joueur réf.)")
    for b in bosses:
        level = TARGET_LEVEL.get(b["code"])
        if level is None:
            continue
        c = compute(level)
        print(f"{b['name']:<26}{c['max_hp']:>12,}{c['attack']:>7}{c['defense']:>7}"
              f"   niv {level} · {c['measured']:,} dégâts/assaut mesurés"
              .replace(",", " "))
        b["max_hp"], b["attack"], b["defense"] = c["max_hp"], c["attack"], c["defense"]
    if write:
        CONTENT.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
        print("\n✅ boss_definitions.json mis à jour")
    else:
        print("\n(dry-run — relancer avec --write pour appliquer)")


if __name__ == "__main__":
    main()
