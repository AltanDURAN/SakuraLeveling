"""Re-stat les mobs de mobs.json — SAISON 1.

Chaque mob est rattaché à un NIVEAU-PALIER et à un archétype ; ses stats sont
recalculées relativement au **joueur de référence** de ce palier (définition
unique : `app/domain/services/reference_player.py`). Préserve image_name,
family, loot_table et spawn_weight.

Invariant non négociable : la DÉFENSE d'un mob ne doit jamais approcher
l'ATTAQUE du joueur. Le combat est soustractif — au-delà, chaque coup tombe au
plancher de 1 dégât et le mob devient increvable.

Usage : .venv/bin/python -m scripts.restat_mobs [--write]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from app.domain.services.reference_player import reference_stats

P = Path(__file__).resolve().parents[1] / "app/infrastructure/content/mobs.json"

#: XP et or d'un mob de palier L (la courbe de progression en dépend —
#: cf. XP_PER_KILL_COEF dans ProgressionService).
XP_PER_LEVEL = 6.25
GOLD_PER_LEVEL = 3


def standard(L: float) -> tuple[float, float, float]:
    """(pv, atk, def) d'un mob standard du palier de niveau L."""
    ref = reference_stats(int(L))
    mdef = 0.45 * ref.attack              # le joueur inflige ~55 % de son ATK
    matk = ref.defense + 0.025 * ref.max_hp   # ~2,5 % des PV du joueur par coup
    mhp = 11 * ref.attack                 # ~20 coups pour le tuer
    return mhp, matk, mdef


def restat(L: float, arch: str) -> dict:
    hp, atk, deff = standard(L)
    spd, cc, cd, dodge = 5, 0, 100, 0
    if arch == "brute":          # tape fort, fragile
        atk *= 1.5; deff *= 0.5; hp *= 0.8
    elif arch == "blinde":       # tank ; DEF capée à 70% ATK joueur (anti-plancher)
        deff = min(deff * 2, 0.70 * reference_stats(int(L)).attack)
        hp *= 1.5; atk *= 0.6
    elif arch == "rapide":       # agit souvent, bursty, fragile
        atk *= 0.9; deff *= 0.8; hp *= 0.6; spd = 9; cc = 20; cd = 150
    return {
        "max_hp": round(hp), "attack": round(atk), "defense": round(deff),
        "speed": spd, "crit_chance": cc, "crit_damage": cd, "dodge": dodge,
        "xp_reward": round(XP_PER_LEVEL * L), "gold_reward": round(GOLD_PER_LEVEL * L),
    }


# (niveau-palier, archétype) par mob.
ASSIGN: dict[str, tuple[int, str]] = {
    # --- Gobelins & slimes (Clairière sinistre, rang F)
    "slime":              (3,  "standard"),
    "gobelin":            (6,  "standard"),
    "gobelin_combattant": (10, "standard"),
    "gobelin_chaman":     (15, "brute"),
    "gobelin_ballon":     (19, "standard"),
    "gobelin_geant":      (23, "blinde"),
    "gobelin_runique":    (27, "brute"),
    "gobelin_assassin":   (31, "rapide"),
    "gobelin_superieur":  (35, "standard"),
    # --- Morts-vivants (Cimetière abandonné, rang E)
    "squelette":          (14, "standard"),
    "zombie":             (18, "blinde"),
    "momie":              (24, "standard"),
    "fantome":            (30, "rapide"),
    "gargouille":         (38, "blinde"),
    "banshee":            (45, "brute"),
    "liche_maudite":      (54, "brute"),
    # --- Démoniaques (Berceau cataclysmique, rang D et au-delà)
    "diablotin":          (44, "rapide"),
    "demon_cornu":        (52, "standard"),
    "ogre_demoniaque":    (62, "brute"),
    "cerbere":            (70, "standard"),
    "succube":            (78, "brute"),
    "ange_dechu":         (87, "standard"),
    "archidemon":         (97, "blinde"),
}


def main() -> None:
    write = "--write" in sys.argv
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
    if write:
        with open(P, "w", encoding="utf-8") as f:
            json.dump(mobs, f, ensure_ascii=False, indent=2)
            f.write("\n")

    print(f"{'code':22s} {'arch':9s} {'L':>3} {'PV':>5} {'ATK':>4} {'DEF':>4} {'XP':>4} {'gold':>4}")
    for m in mobs:
        a = ASSIGN.get(m["code"])
        if not a:
            continue
        print(f"{m['code']:22s} {a[1]:9s} {a[0]:>3} {m['max_hp']:>5} "
              f"{m['attack']:>4} {m['defense']:>4} {m['xp_reward']:>4} {m['gold_reward']:>4}")


    if not write:
        print("\n(dry-run — relancer avec --write pour appliquer)")


if __name__ == "__main__":
    main()
