"""Re-stat les mobs de mobs.json — SAISON 1.

Chaque mob est rattaché à un NIVEAU-PALIER et à un archétype ; ses stats sont
recalculées relativement au **joueur de référence** de ce palier (définition
unique : `app/domain/services/reference_player.py`). Préserve image_name,
family, loot_table et spawn_weight.

Invariant non négociable : la DÉFENSE d'un mob ne doit jamais approcher
l'ATTAQUE du joueur. Le combat est soustractif — au-delà, chaque coup tombe au
plancher de 1 dégât et le mob devient increvable.

ÉLITES DE GROUPE (`GROUP_ELITES`, le plus fort de chaque famille) : stats du
standard de leur palier × `ELITE_MULT`, MESURÉ sur le trio DPS + Tank +
Support de leur niveau (`scripts/reference_roles.py`), capacités comprises.

Usage : .venv/bin/python -m scripts.restat_mobs [--write] [--zones-v2] [--calibrate-elites]
(--zones-v2 : recalage des familles existantes, à l'ouverture des zones C → S ;
 --calibrate-elites : remesure `ELITE_MULT` — à relancer après tout changement
 du moteur, de l'arbre ou des niveaux, puis recopier le résultat ici)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from app.domain.services.reference_player import BASE_SPEED, expected_speed, reference_stats

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


#: Élites de groupe : (×PV, ×ATK) sur le monstre de leur palier. Le plus dur
#: que le trio de leur niveau gagne encore à ≥ 90 % sans mort, capacités
#: comprises — MESURÉ par `--calibrate-elites`, ne pas éditer à la main.
ELITE_MULT: dict[str, tuple[float, float]] = {
    "gobelin_superieur": (3, 3),
    "liche_maudite": (18, 1),
    "aigle_tempete": (8, 1.5),
    "comtesse_ecarlate": (18, 3),
    "dragon_ancien": (26, 0.75),
    "archidemon": (18, 3),
    "avatar_du_neant": (18, 2),
}

#: Une élite rapporte 3× l'XP (à chacun) et l'or (pool partagé) d'un monstre
#: de son palier : un groupe de 3 y passe environ trois fois plus de temps.
ELITE_REWARD_MULT = 3

#: Grilles de la calibration des élites, et critère du trio.
ELITE_HP_GRID = (0.5, 0.75, 1, 1.5, 2, 3, 4, 6, 8, 12, 18, 26)
ELITE_ATK_GRID = (0.5, 0.75, 1, 1.5, 2, 3, 4, 6, 8)
ELITE_MIN_WIN = 0.95      # marge : le trio de calibrage est un build bien construit
ELITE_MAX_DEATHS = 0.2
ELITE_MIN_ACTIONS = 30    # un vrai combat, pas un éclair
ELITE_MAX_ACTIONS = 90    # ~2 min d'animation (1,5 s par action)


def restat(L: float, arch: str, code: str | None = None) -> dict:
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
    # La vitesse suit celle attendue des joueurs du palier (cases de l'arbre).
    spd = round(spd * expected_speed(int(L)) / BASE_SPEED)
    reward = 1
    if code in ELITE_MULT:
        hp_x, atk_x = ELITE_MULT[code]
        hp *= hp_x; atk *= atk_x
        reward = ELITE_REWARD_MULT
    return {
        "max_hp": round(hp), "attack": round(atk), "defense": round(deff),
        "speed": spd, "crit_chance": cc, "crit_damage": cd, "dodge": dodge,
        "xp_reward": round(XP_PER_LEVEL * L * reward),
        "gold_reward": round(GOLD_PER_LEVEL * L * reward),
    }


def as_mob(code: str, stats: dict):
    """dict de stats → MobDefinition (pour les simulations)."""
    from datetime import UTC, datetime

    from app.domain.entities.mob_definition import MobDefinition

    now = datetime.now(UTC)
    return MobDefinition(
        id=0, code=code, name=code, description="", image_name="", family="",
        max_hp=stats["max_hp"], current_hp=stats["max_hp"], attack=stats["attack"],
        defense=stats["defense"], speed=stats["speed"], crit_chance=stats["crit_chance"],
        crit_damage=stats["crit_damage"], dodge=stats["dodge"], hp_regeneration=0,
        xp_reward=0, gold_reward=0, spawn_weight=1, loot_table=None,
        created_at=now, updated_at=now, element="")


def _calibrate_one(code: str):
    """(code, ×PV, ×ATK, ligne de rapport) — le plus dur que le trio gagne encore."""
    from app.domain.services.mob_ability_service import get_mob_abilities
    from scripts.reference_roles import fight

    L, arch = ASSIGN[code]
    base = restat(L, arch)
    abilities = get_mob_abilities(code)

    def mob_at(hp_x, atk_x):
        return as_mob(code, {**base, "max_hp": round(base["max_hp"] * hp_x),
                             "attack": round(base["attack"] * atk_x)})

    # Parmi les réglages que le trio gagne (≥ 95 %, sans mort, 30 à 90
    # actions), celui où son avance sur trois DPS est la plus grande ; à
    # égalité, le plus dur. Choisir « le plus dur » seul donnait parfois un
    # combat éclair gagné par la force brute (ex. frappe de zone ×6 ATK).
    best = None
    for atk_x in ELITE_ATK_GRID:
        for hp_x in ELITE_HP_GRID:
            mob = mob_at(hp_x, atk_x)
            v = fight("DTS", L, mob, abilities, n=20)
            if not (v["win"] >= ELITE_MIN_WIN and v["deaths"] <= ELITE_MAX_DEATHS
                    and ELITE_MIN_ACTIONS <= v["actions"] <= ELITE_MAX_ACTIONS):
                continue
            ddd = fight("DDD", L, mob, abilities, n=20)
            key = (round(v["win"] - ddd["win"], 2), hp_x * atk_x, atk_x)
            if best is None or key > best[0]:
                best = (key, hp_x, atk_x)
    if best is None:
        return code, None, None, f"⚠️  {code} : le trio ne gagne même pas à ×0,5 — capacité à revoir"
    _, hp_x, atk_x = best
    mob = mob_at(hp_x, atk_x)
    cells = {c: fight(c, L, mob, abilities, n=30) for c in ("DTS", "DDD", "DDT", "DDS", "DTT", "TTS", "D")}
    line = " ".join(f"{c} {v['win'] * 100:3.0f}%/{v['deaths']:.1f}m" for c, v in cells.items())
    line += f" | {cells['DTS']['actions']:.0f} actions"
    return code, hp_x, atk_x, f"{code:22s} niv {L:>3} ×PV {hp_x:<4} ×ATK {atk_x:<4} | {line}"


def calibrate_elites() -> dict[str, tuple[float, float]]:
    """Pour chaque élite : le (×PV, ×ATK) que le trio DPS + Tank + Support de
    son niveau gagne à ≥ 95 % sans mort, là où il devance le plus trois DPS."""
    import multiprocessing

    from app.domain.services.mob_ability_service import GROUP_ELITES

    codes = sorted(GROUP_ELITES, key=lambda c: ASSIGN[c][0])
    with multiprocessing.Pool(min(len(codes), multiprocessing.cpu_count())) as pool:
        results = pool.map(_calibrate_one, codes)
    out: dict[str, tuple[float, float]] = {}
    print("Victoires / morts moyennes par composition (D = DPS seul) :")
    for code, hp_x, atk_x, line in results:
        print(line)
        if hp_x is not None:
            out[code] = (hp_x, atk_x)
    return out


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


FARM_ZONES = Path(__file__).resolve().parents[1] / "app/infrastructure/content/farm_zones.json"
#: Rangs des zones prévues : dès que l'une est OUVERTE, le recalage s'applique.
NEW_ZONE_RANKS = ("C", "B", "A", "S")


def zones_v2_open() -> bool:
    """Une zone C → S est-elle ouverte (`farm_zones.json` → `zones`) ? Alors
    les familles existantes sont recalées dans leur tranche (ZONES_V2_LEVELS) :
    le recalage suit le contenu, sans drapeau à retenir."""
    zones = json.loads(FARM_ZONES.read_text(encoding="utf-8")).get("zones", [])
    return any(z.get("rank") in NEW_ZONE_RANKS for z in zones)


if zones_v2_open():
    for _code, _level in ZONES_V2_LEVELS.items():
        ASSIGN[_code] = (_level, ASSIGN[_code][1])


def apply(write: bool) -> list[dict]:
    """Recalcule les stats de chaque monstre d'après ASSIGN (et ELITE_MULT) ;
    `write` : les écrit dans mobs.json. Renvoie les monstres (triés par niveau)."""
    mobs = json.load(open(P, encoding="utf-8"))
    for m in mobs:
        a = ASSIGN.get(m["code"])
        if not a:
            continue
        L, arch = a
        s = restat(L, arch, m["code"])
        m.update(s)
        m["current_hp"] = s["max_hp"]

    mobs.sort(key=lambda m: ASSIGN.get(m["code"], (999, ""))[0])
    if write:
        with open(P, "w", encoding="utf-8") as f:
            json.dump(mobs, f, ensure_ascii=False, indent=2)
            f.write("\n")
    return mobs


def main() -> None:
    write = "--write" in sys.argv
    if "--zones-v2" in sys.argv:
        for code, level in ZONES_V2_LEVELS.items():
            ASSIGN[code] = (level, ASSIGN[code][1])
    if "--calibrate-elites" in sys.argv:
        mult = calibrate_elites()
        print("\nELITE_MULT = {")
        for code, (hp_x, atk_x) in mult.items():
            print(f'    "{code}": ({hp_x}, {atk_x}),')
        print("}\n(à recopier dans scripts/restat_mobs.py, puis relancer avec --write)")
        return
    mobs = apply(write)

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
