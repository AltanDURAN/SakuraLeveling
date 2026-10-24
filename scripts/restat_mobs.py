"""Re-stat les mobs de mobs.json — SAISON 1.

Chaque mob est rattaché à un NIVEAU-PALIER et à un archétype ; ses stats sont
recalculées relativement au **joueur de référence** de ce palier (définition
unique : `app/domain/services/reference_player.py`). Préserve image_name,
family, loot_table et spawn_weight.

Invariant non négociable : la DÉFENSE d'un mob ne doit jamais approcher
l'ATTAQUE du joueur. Le combat est soustractif — au-delà, chaque coup tombe au
plancher de 1 dégât et le mob devient increvable.

Usage : .venv/bin/python -m scripts.restat_mobs [--write] [--zones-v2]
(--zones-v2 : recalage des familles existantes, à l'ouverture des zones C → S)
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
    elif arch == "blinde":       # tank : la plus forte DEF, combat le plus long
        # DEF capée à 60 % de l'ATK joueur, PV ×0,9, ATK ×0,7 : ~47 actions
        # (contre ~39 pour un standard), donc AVANT l'escalade du monstre
        # (action 50). L'ancien réglage (DEF 70 %, PV ×1,5) durait ~95 actions :
        # l'escalade le rendait imbattable en solo, même à son propre palier.
        deff = min(deff * 2, 0.60 * reference_stats(int(L)).attack)
        hp *= 0.9; atk *= 0.7
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
    "slime":              (1,  "standard"),   # premier monstre d'un compte neuf
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
    # --- Sanctuaire primordial (famille primordial)
    "loup_sacre":            (46, "rapide"),
    "cerf_esprit":           (48, "standard"),
    "serpent_des_racines":   (50, "rapide"),
    "ours_colosse":          (52, "brute"),
    "golem_de_mousse":       (54, "blinde"),
    "aigle_tempete":         (56, "rapide"),
    # --- Éclipse éternelle (famille nocturne)
    "chauve_souris_geante":  (57, "rapide"),
    "goule":                 (58, "standard"),
    "loup_garou":            (60, "brute"),
    "sorciere_de_sang":      (62, "brute"),
    "chevalier_de_l_eclipse": (64, "blinde"),
    "vampire_noble":         (66, "standard"),
    "comtesse_ecarlate":     (67, "rapide"),
    # --- Cimes des Wyrms (famille draconique)
    "kobold":                (68, "standard"),
    "dragonnet":             (70, "rapide"),
    "drake_de_braise":       (72, "brute"),
    "wyverne":               (74, "rapide"),
    "dragon_de_givre":       (76, "blinde"),
    "gardien_draconique":    (78, "standard"),
    "dragon_ancien":         (80, "brute"),
    # --- Faille du Néant (famille abyssal)
    "rejeton_du_neant":      (81, "standard"),
    "oeil_errant":           (84, "rapide"),
    "devoreur":              (87, "brute"),
    "heraut_du_vide":        (90, "standard"),
    "kraken_astral":         (93, "blinde"),
    "seraphin_brise":        (96, "brute"),
    "avatar_du_neant":       (100, "standard"),
}


#: RECALAGE des familles existantes dans la plage de leur zone, à appliquer
#: LE JOUR où les zones C → S ouvrent (`--zones-v2`) — décidé avec l'auteur le
#: 24/10/2026. Avant ça, les démons couvrent seuls la fin de partie (jusqu'au
#: niveau 97) : les recaler plus tôt laisserait un joueur de niveau 60 sans
#: monstre à sa mesure. Rangs atteints par le joueur de référence : F 1–20,
#: E 21–33, D 34–45, C 46–56, B 57–67, A 68–80, S 81–100.
ZONES_V2_LEVELS: dict[str, int] = {
    # Clairière sinistre (F)
    "slime": 1, "gobelin": 3, "gobelin_combattant": 5, "gobelin_chaman": 8,
    "gobelin_ballon": 10, "gobelin_geant": 12, "gobelin_runique": 15,
    "gobelin_assassin": 17, "gobelin_superieur": 20,
    # Cimetière abandonné (E)
    "squelette": 21, "zombie": 23, "momie": 25, "fantome": 27,
    "gargouille": 29, "banshee": 31, "liche_maudite": 33,
    # Berceau cataclysmique (D)
    "diablotin": 34, "demon_cornu": 36, "ogre_demoniaque": 38, "cerbere": 40,
    "succube": 42, "ange_dechu": 44, "archidemon": 45,
}


def main() -> None:
    write = "--write" in sys.argv
    if "--zones-v2" in sys.argv:
        for code, level in ZONES_V2_LEVELS.items():
            ASSIGN[code] = (level, ASSIGN[code][1])
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
