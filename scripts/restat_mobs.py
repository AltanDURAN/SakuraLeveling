"""Re-stat les mobs de mobs.json selon les formules de palier V2.

Chaque mob est assigné à un niveau-palier + un archétype ; ses stats de combat
et récompenses sont recalculées relativement au joueur de référence (Contrainte
soustractive : DEF mob ≈ 45% ATK joueur, etc.). Préserve image_name / family /
loot_table / spawn_weight existants.

Régénère / ajuste : éditer ASSIGN puis relancer
    .venv/bin/python scripts/restat_mobs.py
"""

from __future__ import annotations

import json
from pathlib import Path

P = Path(__file__).resolve().parents[1] / "app/infrastructure/content/mobs.json"


# Courbe du joueur de référence (build équilibré) — base de calibrage.
def p_atk(L: float) -> float:
    return 10 + 1.45 * L


def p_def(L: float) -> float:
    return 8 + 0.52 * L


def p_pv(L: float) -> float:
    return 100 + 16 * L


def standard(L: float) -> tuple[float, float, float]:
    """(hp, atk, def) d'un mob standard du palier de niveau L."""
    mdef = 0.45 * p_atk(L)               # joueur inflige ~55% de son ATK
    matk = p_def(L) + 0.025 * p_pv(L)    # ~2.5% des PV joueur par coup
    mhp = 11 * p_atk(L)                  # ~20 coups joueur pour tuer
    return mhp, matk, mdef


def restat(L: float, arch: str) -> dict:
    hp, atk, deff = standard(L)
    spd, cc, cd, dodge = 5, 0, 100, 0
    if arch == "brute":          # tape fort, fragile
        atk *= 1.5; deff *= 0.5; hp *= 0.8
    elif arch == "blinde":       # tank ; DEF capée à 70% ATK joueur (anti-plancher)
        deff = min(deff * 2, 0.70 * p_atk(L)); hp *= 1.5; atk *= 0.6
    elif arch == "rapide":       # agit souvent, bursty, fragile
        atk *= 0.9; deff *= 0.8; hp *= 0.6; spd = 9; cc = 20; cd = 150
    return {
        "max_hp": round(hp), "attack": round(atk), "defense": round(deff),
        "speed": spd, "crit_chance": cc, "crit_damage": cd, "dodge": dodge,
        "xp_reward": round(6.25 * L), "gold_reward": round(3 * L),
    }


# (niveau-palier, archétype) par mob.
ASSIGN: dict[str, tuple[int, str]] = {
    "slime":              (3,  "standard"),   # F-
    "gobelin":            (8,  "standard"),   # F
    "gobelin_combattant": (13, "standard"),   # F+
    "gobelin_chaman":     (23, "brute"),      # E  (caster glass)
    "gobelin_assassin":   (23, "rapide"),     # E
    "gobelin_ballon":     (28, "standard"),   # E+
    "gobelin_geant":      (33, "blinde"),     # D- (tank)
    "gobelin_runique":    (38, "brute"),      # D
    "gobelin_superieur":  (48, "standard"),   # C-
}


def main() -> None:
    mobs = json.load(open(P, encoding="utf-8"))
    for m in mobs:
        a = ASSIGN.get(m["code"])
        if not a:
            continue
        L, arch = a
        s = restat(L, arch)
        m.update(s)
        m["current_hp"] = s["max_hp"]

    mobs.sort(key=lambda m: ASSIGN.get(m["code"], (999, ""))[0])
    json.dump(mobs, open(P, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    print(f"{'code':22s} {'arch':9s} {'L':>3} {'PV':>5} {'ATK':>4} {'DEF':>4} {'XP':>4} {'gold':>4}")
    for m in mobs:
        a = ASSIGN.get(m["code"])
        if not a:
            continue
        print(f"{m['code']:22s} {a[1]:9s} {a[0]:>3} {m['max_hp']:>5} "
              f"{m['attack']:>4} {m['defense']:>4} {m['xp_reward']:>4} {m['gold_reward']:>4}")


if __name__ == "__main__":
    main()
