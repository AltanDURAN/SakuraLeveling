"""Génère et calibre les 100 étages de la tour solo → `tower_floors.json`.

Décidé avec l'auteur (27/10/2026) : les étages sont les MÊMES pour tout le
monde ; l'étage N est du niveau N (toute la durée du jeu) ; chaque étage
oppose 1 à 4 monstres, un boss tous les 10 étages. Les monstres suivent la
logique de niveau de leur zone (l'étage tire d'abord dans la zone de son
niveau), mais n'importe quel monstre peut revenir en renfort dans un groupe
(« invités ») — et certains étages sont des COMBINAISONS choisies à la main
(`COMBOS`), pensées pour obliger à adapter son build.

Stats : chaque monstre est re-staté au niveau de l'étage avec son archétype
(`restat_mobs.restat`), puis TOUT l'étage est multiplié par un facteur k (PV
et ATK) mesuré par simulation : le GÉNÉRALISTE de `reference_roles` au niveau
de l'étage, seul, à PV pleins, gagne `TARGET_WIN` de ses combats (`BOSS_WIN`
contre un boss). Le reste (`_mesure`) : réussite des quatre profils au niveau
de l'étage et cinq niveaux plus tard.

Usage : .venv/bin/python -m scripts.build_tower [--write] [--floors 1-20]
"""

from __future__ import annotations

import json
import math
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTENT = ROOT / "app/infrastructure/content"
OUT = CONTENT / "tower_floors.json"

TARGET_WIN = 0.65
BOSS_WIN = 0.50
SIMULATIONS = 30
SEARCH_STEPS = 7
K_RANGE = (0.10, 3.0)
#: Étages au facteur imposé : le premier se franchit avec un compte tout neuf
#: (le premier monstre du jeu, sans renfort — test `test_un_compte_neuf…`).
FIXED_K = {1: 1.0}

#: Tranche de niveaux de chaque zone (joueur de référence) et ses familles.
ZONE_BANDS: tuple[tuple[int, int, tuple[str, ...]], ...] = (
    (1, 20, ("slime", "gobelin")),
    (21, 33, ("mort-vivant",)),
    (34, 45, ("demoniaque",)),
    (46, 56, ("primordial",)),
    (57, 67, ("nocturne",)),
    (68, 80, ("draconique",)),
    (81, 100, ("abyssal",)),
)

#: Nombre de monstres selon la place dans la dizaine (le 10e est le boss).
PATTERN = {1: 1, 2: 2, 3: 1, 4: 2, 5: 3, 6: 2, 7: 3, 8: 2, 9: 4}
#: Exclus des tirages : le charme de la succube est une défaite immédiate
#: seul (sauf Volonté de fer) — un mur, pas un défi d'adaptation.
EXCLUDED = {"succube"}
GUEST_CHANCE = 0.25

#: Boss : (code, escorte). Le boss a ×3 PV et ×1,25 ATK avant calibrage,
#: l'escorte ×0,6 PV — puis tout l'étage est calibré ensemble.
BOSSES: dict[int, tuple[str, str, tuple[str, ...]]] = {
    10: ("Le chef de clan", "gobelin_superieur", ()),
    20: ("La crypte de la liche", "liche_maudite", ("squelette",)),
    30: ("L'ange déchu", "ange_dechu", ("diablotin", "diablotin")),
    40: ("Le trône de l'archidémon", "archidemon", ("demon_cornu", "ogre_demoniaque")),
    50: ("L'œil de la tempête", "aigle_tempete", ("loup_sacre", "loup_sacre")),
    60: ("Le bal de la comtesse", "comtesse_ecarlate", ("chauve_souris_geante", "vampire_noble")),
    70: ("Le serment des cimes", "gardien_draconique", ("kobold", "kobold")),
    80: ("Le dragon ancien", "dragon_ancien", ("dragonnet", "drake_de_braise")),
    90: ("Le séraphin brisé", "seraphin_brise", ("rejeton_du_neant", "oeil_errant")),
    100: ("Le cœur du Néant", "avatar_du_neant", ("heraut_du_vide", "devoreur")),
}

#: Combinaisons choisies : (nom, monstres dans l'ordre de la formation).
COMBOS: dict[int, tuple[str, tuple[str, ...]]] = {
    1: ("Le premier pas", ("slime",)),
    4: ("Les éclaireurs", ("gobelin", "gobelin_combattant")),
    8: ("Le chaman et sa garde", ("gobelin_combattant", "gobelin_chaman")),
    14: ("Pluie de ballons", ("gobelin_ballon", "gobelin_ballon", "gobelin_ballon")),
    17: ("Le piège runique", ("gobelin_assassin", "gobelin_runique", "gobelin_runique")),
    23: ("La horde", ("squelette", "zombie", "zombie", "squelette")),
    26: ("Cortège funèbre", ("momie", "banshee")),
    29: ("Pierre et brume", ("gargouille", "fantome", "fantome")),
    36: ("Cercle infernal", ("diablotin", "demon_cornu", "diablotin")),
    39: ("Le chenil", ("ogre_demoniaque", "cerbere")),
    47: ("La meute sacrée", ("loup_sacre", "loup_sacre", "loup_sacre")),
    53: ("Racines et mousse", ("serpent_des_racines", "golem_de_mousse")),
    58: ("La nuée", ("chauve_souris_geante", "chauve_souris_geante",
                     "chauve_souris_geante", "chauve_souris_geante")),
    63: ("Le pacte écarlate", ("sorciere_de_sang", "vampire_noble")),
    65: ("La garde d'éclipse", ("chevalier_de_l_eclipse", "chevalier_de_l_eclipse")),
    71: ("La couvée", ("dragonnet", "dragonnet", "dragonnet")),
    75: ("Ciel de braise", ("wyverne", "drake_de_braise")),
    78: ("Les gardiens des cimes", ("dragon_de_givre", "gardien_draconique")),
    85: ("Ce qui regarde", ("rejeton_du_neant", "oeil_errant", "rejeton_du_neant")),
    88: ("Le festin", ("goule", "devoreur", "goule")),
    93: ("Marée astrale", ("kraken_astral", "heraut_du_vide")),
    97: ("Le chœur brisé", ("rejeton_du_neant", "seraphin_brise", "heraut_du_vide")),
}


def _load(name: str):
    return json.loads((CONTENT / name).read_text(encoding="utf-8"))


def _restat():
    from scripts import restat_mobs
    return restat_mobs


def zone_families(level: int) -> tuple[str, ...]:
    return next(f for lo, hi, f in ZONE_BANDS if lo <= level <= hi)


def _element(code: str, rng: random.Random, mobs: dict, weights: dict, zone_elements: dict) -> str:
    w = weights.get(code) or {}
    if w:
        elems = sorted(w)
        return rng.choices(elems, weights=[w[e] for e in elems], k=1)[0]
    family = mobs[code].get("family", "")
    pool = zone_elements.get(family) or []
    if pool:
        return rng.choice(sorted(pool))
    return mobs[code].get("element", "") or ""


def compose(floor: int) -> tuple[str, list[str], str | None]:
    """(nom, monstres, boss) de l'étage — déterministe."""
    from app.domain.services.mob_ability_service import GROUP_ELITES
    from app.domain.services.tower_service import floor_level, is_boss_floor

    if is_boss_floor(floor):
        name, boss, escort = BOSSES[floor]
        return name, [boss, *escort], boss
    if floor in COMBOS:
        name, codes = COMBOS[floor]
        return name, list(codes), None
    assign = _restat().ASSIGN
    mobs = {m["code"]: m for m in _load("mobs.json")}
    level = floor_level(floor)
    rng = random.Random(f"tour-{floor}")
    n = PATTERN[floor % 10]
    n = min(n, 2 if floor < 10 else 3 if floor < 20 else 4)
    usable = [c for c in assign if c in mobs and c not in GROUP_ELITES and c not in EXCLUDED]
    home = [c for c in usable if mobs[c]["family"] in zone_families(level) and assign[c][0] <= level + 3]
    if not home:
        home = [c for c in usable if mobs[c]["family"] in zone_families(level)]
    guests = [c for c in usable if assign[c][0] < level - 3 and c not in home]
    codes = [
        rng.choice(guests) if guests and floor > 10 and rng.random() < GUEST_CHANCE else rng.choice(home)
        for _ in range(n)
    ]
    return "", codes, None


def enemies_for(floor: int, k: float) -> list[dict]:
    """Ennemis de l'étage avec leurs stats (facteur k appliqué)."""
    from app.domain.services.tower_service import floor_level

    restat_mobs = _restat()
    mobs = {m["code"]: m for m in _load("mobs.json")}
    weights = _load("mob_element_weights.json").get("weights", {})
    zones = _load("farm_zones.json")
    zone_elements: dict[str, list[str]] = {}
    for z in zones.get("zones", []) + zones.get("planned_zones", []):
        elems = z.get("elements") or [s.get("element") for s in z.get("spots", []) if s.get("element")]
        for fam in z.get("families", []):
            zone_elements[fam] = elems
    name, codes, boss = compose(floor)
    level = floor_level(floor)
    rng = random.Random(f"tour-elements-{floor}")
    out = []
    for code in codes:
        s = restat_mobs.restat(level, restat_mobs.ASSIGN[code][1])
        hp_x, atk_x = (3.0, 1.25) if code == boss else ((0.6, 1.0) if boss else (1.0, 1.0))
        out.append({
            "code": code, "name": mobs[code]["name"], "family": mobs[code]["family"],
            "image_name": mobs[code].get("image_name", ""),
            "element": _element(code, rng, mobs, weights, zone_elements),
            "boss": code == boss and not any(e["boss"] for e in out),
            "max_hp": max(1, round(s["max_hp"] * hp_x * k)),
            "attack": max(1, round(s["attack"] * atk_x * k)),
            "defense": s["defense"], "speed": s["speed"],
            "crit_chance": s["crit_chance"], "crit_damage": s["crit_damage"], "dodge": s["dodge"],
        })
    return out


def win_rate(floor: int, enemies: list[dict], compo: str = "G", level: int | None = None,
             n: int = SIMULATIONS) -> float:
    from app.domain.services.party_combat_service import PartyCombatService
    from app.domain.services.tower_service import enemy_setups, floor_level
    from scripts.reference_roles import party

    level = level or floor_level(floor)
    wins = 0
    for seed in range(n):
        random.seed(seed)
        members, passives, tactics = party(compo, min(100, level))
        result = PartyCombatService().fight_party_vs_mobs(
            members, enemy_setups(enemies), passives_by_player=passives,
            tactics_by_player=tactics)
        wins += result.victory
    return wins / n


def calibrate(floor: int) -> dict:
    from app.domain.services.tower_service import floor_level, is_boss_floor

    target = BOSS_WIN if is_boss_floor(floor) else TARGET_WIN
    lo, hi = math.log(K_RANGE[0]), math.log(K_RANGE[1])
    best = FIXED_K.get(floor, K_RANGE[0])
    for _ in range(0 if floor in FIXED_K else SEARCH_STEPS):
        mid = (lo + hi) / 2
        if win_rate(floor, enemies_for(floor, math.exp(mid))) >= target:
            best, lo = math.exp(mid), mid
        else:
            hi = mid
    k = round(best, 3)
    enemies = enemies_for(floor, k)
    level = floor_level(floor)
    name, _, _ = compose(floor)
    mesure = {c: round(win_rate(floor, enemies, c, n=20), 2) for c in "DTSG"}
    mesure.update({f"{c}+5": round(win_rate(floor, enemies, c, level + 5, n=20), 2) for c in "DTSG"})
    return {"floor": floor, "level": level, "boss": is_boss_floor(floor), "name": name,
            "k": k, "enemies": enemies, "_mesure": mesure}


def main() -> None:
    import multiprocessing

    write = "--write" in sys.argv
    floors = range(1, 101)
    if "--floors" in sys.argv:
        a, _, b = sys.argv[sys.argv.index("--floors") + 1].partition("-")
        floors = range(int(a), int(b or a) + 1)
    with multiprocessing.Pool() as pool:
        built = pool.map(calibrate, floors)
    for f in built:
        m = f["_mesure"]
        names = ", ".join(e["name"] for e in f["enemies"])
        print(f"{f['floor']:>3} niv {f['level']:>3} k {f['k']:<5} | "
              + " ".join(f"{c} {m[c]:.0%}/{m[c + '+5']:.0%}" for c in "DTSG")
              + f" | {f['name'] or '—'} : {names}")
    if write:
        existing = {f["floor"]: f for f in json.loads(OUT.read_text(encoding="utf-8")).get("floors", [])} \
            if OUT.exists() else {}
        existing.update({f["floor"]: f for f in built})
        payload = {
            "_comment": (
                "Tour solo : 100 étages, les mêmes pour tous (l'étage N est du niveau N, "
                "un boss tous les 10). Généré et calibré par scripts/build_tower.py — ne pas "
                "éditer les stats à la main : le généraliste du niveau de l'étage, seul, à "
                f"PV pleins, gagne {TARGET_WIN:.0%} de ses combats ({BOSS_WIN:.0%} contre un boss). "
                "`_mesure` : réussite des profils D/T/S/G à ce niveau et 5 niveaux plus tard."
            ),
            "floors": [existing[k] for k in sorted(existing)],
        }
        OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"\n✅ écrit dans {OUT}")
    else:
        print("\n(aperçu — relancer avec --write pour écrire tower_floors.json)")


if __name__ == "__main__":
    main()
