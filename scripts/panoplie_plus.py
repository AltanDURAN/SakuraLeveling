"""Rééquilibrage des panoplies (power score ÉGAL entre familles) + système "+".

Objectif (retour joueurs) : deux panoplies différentes doivent donner ~le même
SCORE DE PUISSANCE, tout en gardant leur ARCHÉTYPE (fer=def, gobelin=crit,
slime=PV/régen, cuir=esquive, lin=dégâts crit). Les stats rares (vitesse, crit,
esquive) restent limitées sans rendre une panoplie plus forte.

Le score de puissance valorise très inégalement les stats (1 DEF = 25 PV
effectifs ; PV/régen/dég.crit ≈ 0 par point). On calibre donc les TOTAUX de
chaque famille pour qu'un set complet (12 pièces + bonus) sur un débutant
donne ~le même score. Vérification imprimée en fin de script.

Aussi : armes/boucliers re-statés (toutes familles), versions "+" gobelin/slime
(stats ×1.5), ressources (sang gobelin/slime, infuseur), drops, infuseur au shop.

Idempotent. .venv/bin/python scripts/panoplie_plus.py
"""

from __future__ import annotations

import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "app/infrastructure/content"
ITEMS, CRAFTS, SETS, SHOP, MOBS = (ROOT / f for f in
    ["items.json", "crafts.json", "sets.json", "shop_items.json", "mobs.json"])

_RARITY_UP = {"common": "uncommon", "uncommon": "rare", "rare": "epic",
              "epic": "legendary", "legendary": "legendary"}


def _load(p): return json.load(open(p, encoding="utf-8"))
def _save(p, d): json.dump(d, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=2)


# ---- Slots & poids de répartition du thème sur armures/accessoires ----
ARMOR_ACC = {  # slot -> poids
    "casque": 1.0, "plastron": 1.2, "jambieres": 1.0, "bottes": 0.8,
    "collier": 0.95, "bague": 0.95, "bracelet": 0.7, "ceinture": 0.7,
    "cape": 0.8, "boucle_oreille": 0.7,
}
_W_SUM = sum(ARMOR_ACC.values())

# Arme 1-main et bouclier 1-main par famille (cœur universel attaque/défense +
# une touche thématique pour que toute arme tape et tout bouclier protège).
# Cœur UNIVERSEL (attaque 6 / défense 5 identiques) + petite touche thématique,
# pour que toute arme tape et tout bouclier protège, sans déséquilibrer.
WEAPON_1H = {
    "iron":    {"attack": 8, "defense": 1},
    "gobelin": {"attack": 8, "crit_chance": 2},
    "slime":   {"attack": 8, "max_hp": 4},
    "leather": {"attack": 8, "dodge": 1},
    "linen":   {"attack": 8, "crit_damage": 4},
}
SHIELD_1H = {
    "iron":    {"defense": 7, "max_hp": 4},
    "gobelin": {"defense": 7, "crit_chance": 1},
    "slime":   {"defense": 7, "max_hp": 6},
    "leather": {"defense": 7, "dodge": 2},
    "linen":   {"defense": 7, "crit_damage": 2},
}
# Thème réparti sur les 10 slots armures/accessoires (totaux calibrés pour
# un power score égal — voir vérification). Distribué par poids ARMOR_ACC.
THEME_TOTAL = {
    "iron":    {"max_hp": 110},
    "gobelin": {"attack": 8, "crit_chance": 6, "crit_damage": 6},
    "slime":   {"max_hp": 200, "hp_regeneration": 6},
    "leather": {"dodge": 16, "max_hp": 150},
    "linen":   {"crit_damage": 44, "crit_chance": 16, "attack": 4},
}
# Bonus de set (12 pièces) — thématique. Tiers 2/4/8/12.
SET_BONUS = {
    "iron":    ("defense_flat", [1, 3, 5, 7]),
    "gobelin": ("crit_chance_flat", [1, 2, 3, 4]),
    "slime":   ("hp_regeneration_flat", [4, 8, 13, 18]),
    "leather": ("dodge_flat", [1, 2, 4, 6]),
    "linen":   ("crit_damage_flat", [3, 6, 9, 14]),
}
SET_META = {
    "iron":    ("Fer", "Armure lourde et fiable, taillée pour encaisser.", "🛡️", "#9aa0aa"),
    "gobelin": ("Gobeline", "Fourbe et vicieuse : frappe critique accrue.", "👹", "#7ba85a"),
    "slime":   ("Slime", "Imprégnée de gelée régénératrice.", "🟢", "#8fdc70"),
    "leather": ("Cuir", "Souple et légère, favorise l'esquive.", "🟫", "#a07040"),
    "linen":   ("Lin", "Tissée pour amplifier les coups critiques.", "⬜", "#d8d0c0"),
}


TARGET_POWER = 290  # power score visé pour un set complet sur un débutant

_STAT_KEY = {"attack": "atk", "defense": "deff", "max_hp": "hp",
             "crit_chance": "cc", "crit_damage": "cd", "dodge": "dodge", "speed": "spd"}


def _power(atk, deff, hp, cc, cd, dodge, spd):
    crit = (cc / 100) * max(0, cd - 100) / 100
    off = atk * (1 + crit) * (1 + spd / 100)
    ehp = (hp + deff * 25) / max(0.01, 1 - dodge / 100)
    return off * ehp / 42


# Slots ordonnés par poids décroissant (les gros items se remplissent en premier).
_SLOTS_ORDERED = sorted(ARMOR_ACC, key=lambda s: -ARMOR_ACC[s])
_CHUNK = 2  # valeur visée par stat posée → +2 net plutôt qu'un +1 éparpillé


def distribute_theme(theme):
    """Concentre chaque stat sur PEU de slots (valeurs ~_CHUNK) en préservant le
    TOTAL par stat. Une rotation place chaque stat sur des slots différents, si
    bien qu'un item porte 1-2 stats nettes au lieu d'un +1 partout.
    Retourne {slot: {stat: val}}."""
    out = {s: {} for s in ARMOR_ACC}
    n = len(_SLOTS_ORDERED)
    ptr = 0
    for stat, total in theme.items():
        total = int(round(total))
        if total <= 0:
            continue
        k = max(1, min(n, total // _CHUNK))   # nb de slots ciblés (chunk ≈ 2)
        base, extra = divmod(total, k)         # divmod préserve le total exactement
        for i in range(k):
            slot = _SLOTS_ORDERED[(ptr + i) % n]
            val = base + (1 if i < extra else 0)
            if val:
                out[slot][stat] = out[slot].get(stat, 0) + val
        ptr = (ptr + k) % n

    # Aucun slot d'armure vide : on DÉPLACE 1 pt d'un slot riche (≥2) vers chaque
    # vide. Préserve le total par stat → power score inchangé. (Cas typique : fer,
    # dont le budget d'armure est minime car sa def vit surtout dans bouclier+set.)
    empties = [s for s in ARMOR_ACC if not out[s]]
    for empty in empties:
        donor = max(out, key=lambda s: max(out[s].values(), default=0))
        if not out[donor] or max(out[donor].values()) < 2:
            break  # plus rien à déplacer proprement (budget épuisé)
        stat = max(out[donor], key=out[donor].get)
        out[donor][stat] -= 1
        if out[donor][stat] == 0:
            del out[donor][stat]
        out[empty][stat] = out[empty].get(stat, 0) + 1
    return out


def _distributed_total(theme):
    """Somme RÉELLE du thème après distribution (pour l'autotune)."""
    agg = {}
    for slot_stats in distribute_theme(theme).values():
        for k, v in slot_stats.items():
            agg[k] = agg.get(k, 0) + v
    return agg


def _set_totals(fam, theme_distributed):
    """Stats totales : base + arme1H + bouclier1H + thème distribué + bonus set."""
    tot = dict(atk=10, deff=5, hp=100, cc=5, cd=150, dodge=0, spd=5)
    for sb in [WEAPON_1H[fam], SHIELD_1H[fam], theme_distributed]:
        for k, v in sb.items():
            if _STAT_KEY.get(k):
                tot[_STAT_KEY[k]] += v
    typ, vals = SET_BONUS[fam]
    sk = _STAT_KEY.get(typ.replace("_flat", ""))
    if sk:
        tot[sk] += vals[-1]
    return tot


def _autotune_theme():
    """Échelonne THEME_TOTAL (binary search, sur les totaux DISTRIBUÉS réels)
    pour que chaque set complet atteigne TARGET_POWER → power score égal."""
    for fam, theme in THEME_TOTAL.items():
        lo, hi = 0.0, 8.0
        for _ in range(44):
            mid = (lo + hi) / 2
            scaled = {k: v * mid for k, v in theme.items()}
            dist = _distributed_total(scaled)
            if _power(**_set_totals(fam, dist)) < TARGET_POWER:
                lo = mid
            else:
                hi = mid
        f = (lo + hi) / 2
        THEME_TOTAL[fam] = {k: round(v * f) for k, v in theme.items()}


def two_hand(stats_1h, malus_stat, malus_val):
    """Version 2-mains ≈ ×1.9 + un malus (occupe 2 slots)."""
    out = {k: math.ceil(v * 1.9) for k, v in stats_1h.items()}
    out[malus_stat] = out.get(malus_stat, 0) - malus_val
    return out


def plus_stats(sb):
    return {k: (math.ceil(v * 1.5) if v > 0 else v) for k, v in (sb or {}).items()}


# Malus 2-mains par famille (stat, valeur)
TWO_HAND_MALUS = {
    "iron": ("speed", 2), "gobelin": ("crit_chance", 2), "slime": ("defense", 3),
    "leather": ("defense", 2), "linen": ("defense", 3),
}


def main() -> None:
    items = _load(ITEMS)
    by_code = {i["code"]: i for i in items}

    def ensure_item(entry):
        if entry["code"] in by_code:
            by_code[entry["code"]].update(entry)
        else:
            items.append(entry); by_code[entry["code"]] = entry

    def resource(code, name, desc, rarity, buy_price=None):
        ensure_item({"code": code, "name": name, "description": desc,
            "category": "resource", "rarity": rarity, "stackable": True,
            "max_stack": None, "sell_price": 0, "buy_price": buy_price, "icon": None,
            "stat_bonuses": None, "equipment_slot": None,
            "requires_two_hands": False, "family": ""})

    # 1. Ressources
    resource("sang_gobelin_hq", "Sang de gobelin de haute qualité",
             "Sang rare prélevé sur les gobelins d'élite. Infuse l'équipement gobelin.", "rare")
    resource("sang_slime", "Sang de slime",
             "Essence visqueuse rare distillée des slimes. Infuse l'équipement slime.", "rare")
    resource("infuseur", "Infuseur",
             "Catalyseur d'infusion. Améliore un équipement de panoplie. Achetable en boutique.",
             "uncommon", buy_price=1000)

    # 2. Rééquilibrage de TOUS les équipements de famille
    _autotune_theme()   # calibre THEME_TOTAL pour un power score égal
    FAMILIES = ("iron", "gobelin", "slime", "leather", "linen")
    dist_by_fam = {fam: distribute_theme(THEME_TOTAL[fam]) for fam in FAMILIES}
    for it in items:
        fam, slot, cat = it.get("family"), it.get("equipment_slot"), it.get("category")
        if fam not in FAMILIES:
            continue
        is_2h = bool(it.get("requires_two_hands"))
        if cat == "weapon":
            base = WEAPON_1H[fam]
            it["stat_bonuses"] = (two_hand(base, *TWO_HAND_MALUS[fam]) if is_2h else dict(base))
        elif cat == "shield":
            base = SHIELD_1H[fam]
            # 2-mains bouclier : malus en attaque
            it["stat_bonuses"] = (two_hand(base, "attack", 4) if is_2h else dict(base))
        elif slot in ARMOR_ACC:
            it["stat_bonuses"] = dict(dist_by_fam[fam].get(slot, {}))

    # 3. Versions "+" gobelin/slime + recettes
    plus_recipes = []
    for fam, sang in [("gobelin", "sang_gobelin_hq"), ("slime", "sang_slime")]:
        for base in [i for i in list(items) if i.get("family") == fam]:
            pcode = base["code"] + "_plus"
            ensure_item({**base, "code": pcode, "name": base["name"] + " +",
                "description": base["description"] + " — version infusée (améliorée).",
                "rarity": _RARITY_UP.get(base.get("rarity", "common"), "rare"),
                "family": fam + "_plus",
                "stat_bonuses": plus_stats(base.get("stat_bonuses")),
                "sell_price": int((base.get("sell_price") or 0) * 2)})
            plus_recipes.append({"code": pcode + "_recipe", "name": base["name"] + " +",
                "result_item_code": pcode, "result_quantity": 1,
                "ingredients": [{"item_code": base["code"], "quantity": 1},
                                {"item_code": sang, "quantity": 1},
                                {"item_code": "infuseur", "quantity": 1}]})
    _save(ITEMS, items)

    # 4. Recettes "+"
    crafts = [r for r in _load(CRAFTS) if not r["code"].endswith("_plus_recipe")]
    crafts += plus_recipes
    _save(CRAFTS, crafts)

    # 5. Bonus de set (base + versions "+" légèrement supérieures)
    sets = _load(SETS)
    for fam in FAMILIES:
        typ, vals = SET_BONUS[fam]
        name, desc, icon, color = SET_META[fam]
        sets[fam] = {"name": name, "description": desc, "icon": icon, "color": color,
            "tiers": [{"min_pieces": mp, "type": typ, "value": v}
                      for mp, v in zip([2, 4, 8, 12], vals)]}
    for fam, base in [("gobelin", "gobelin"), ("slime", "slime")]:
        typ, vals = SET_BONUS[base]
        name, desc, icon, color = SET_META[base]
        sets[fam + "_plus"] = {"name": name + " +",
            "description": desc + " Version infusée.", "icon": icon, "color": color,
            "tiers": [{"min_pieces": mp, "type": typ, "value": math.ceil(v * 1.4)}
                      for mp, v in zip([2, 4, 8, 12], vals)]}
    _save(SETS, sets)

    # 6. Infuseur au shop (1000 or)
    shop = _load(SHOP)
    if not any(s["item_code"] == "infuseur" for s in shop):
        shop.append({"item_code": "infuseur", "buy_price": 1000, "max_sell_price": 0,
                     "min_sell_price": 0, "stock_threshold": 100, "enabled": True})
    _save(SHOP, shop)

    # 7. Drops rares (0/1, ~5× plus rares qu'une dent/slime ball → 0.15)
    mobs = _load(MOBS)
    mob_by = {m["code"]: m for m in mobs}
    def add_drop(mc, ic, rate):
        m = mob_by.get(mc)
        if not m: return
        lt = [e for e in (m.get("loot_table") or []) if e.get("item_code") != ic]
        lt.append({"item_code": ic, "drop_rate": rate, "min_quantity": 1, "max_quantity": 1})
        m["loot_table"] = lt
    add_drop("gobelin_superieur", "sang_gobelin_hq", 0.15)
    add_drop("gobelin_assassin", "sang_gobelin_hq", 0.15)
    add_drop("slime", "sang_slime", 0.15)
    _save(MOBS, mobs)

    _verify(FAMILIES)


def _verify(families):
    """Power score d'un set complet (débutant + 12 pièces + bonus), par famille."""
    base = _power(atk=10, deff=5, hp=100, cc=5, cd=150, dodge=0, spd=5)
    print(f"\n{'famille':10s} {'power set complet':>18s}  (base seul = %.0f)" % base)
    for fam in families:
        dist = _distributed_total(THEME_TOTAL[fam])
        print(f"{fam:10s} {round(_power(**_set_totals(fam, dist)), 1):>18}")


if __name__ == "__main__":
    main()
