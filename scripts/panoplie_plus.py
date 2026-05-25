"""Rééquilibrage des armes/équipements + système de panoplies "+".

- Rééquilibre les stats des armes/boucliers (toutes familles) et des
  équipements gobelin/slime, cohérent avec l'équilibrage V2 (modeste, parité
  attaque/défense).
- Crée les ressources : sang de gobelin de haute qualité, sang de slime, infuseur.
- Ajoute les drops rares (5× plus rares qu'une dent/slime ball, 0 ou 1) :
  sang_gobelin_hq sur gobelin_superieur + gobelin_assassin, sang_slime sur slime.
- Génère les versions "+" (gobelin_plus / slime_plus) : stats de l'item de base
  légèrement augmentées (×1.5), famille dédiée, rareté supérieure.
- Recettes : chaque "+" = item de base ×1 + sang ×1 + infuseur ×1 (forge/craft).
- Bonus de panoplie gobelin_plus / slime_plus (légèrement > base).
- Infuseur au /shop à 1000 or.

Idempotent : relançable. .venv/bin/python scripts/panoplie_plus.py
"""

from __future__ import annotations

import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "app/infrastructure/content"
ITEMS = ROOT / "items.json"
CRAFTS = ROOT / "crafts.json"
SETS = ROOT / "sets.json"
SHOP = ROOT / "shop_items.json"
MOBS = ROOT / "mobs.json"

_RARITY_UP = {"common": "uncommon", "uncommon": "rare", "rare": "epic",
              "epic": "legendary", "legendary": "legendary"}


def _load(p):
    return json.load(open(p, encoding="utf-8"))


def _save(p, data):
    json.dump(data, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=2)


# ============ 1. Rééquilibrage des stats (par code) ============
# Armes (1 main) : stat offensive principale + thème de famille.
# Armes (2 mains) : ~2.3× + malus thématique.
WEAPON_STATS = {
    "wood_sword": {"attack": 4},
    "hunter_dagger": {"attack": 4, "crit_chance": 5},
    "gobelin_axe": {"attack": 7, "crit_damage": 8},
    "gobelin_blade": {"attack": 6, "crit_chance": 3, "crit_damage": 6},
    "gobelin_greataxe": {"attack": 17, "crit_damage": 14, "crit_chance": -2, "defense": -3},
    "slime_blade": {"attack": 6, "max_hp": 6},
    "slime_morningstar": {"attack": 5, "hp_regeneration": 2, "max_hp": 4},
    "slime_greatblade": {"attack": 15, "max_hp": -8, "defense": -4},
    "iron_dagger": {"attack": 5, "speed": 2, "crit_chance": 2},
    "iron_sword": {"attack": 6, "defense": 2, "max_hp": 4},
    "iron_greatsword": {"attack": 14, "speed": 5, "crit_chance": 5, "defense": -5, "dodge": -2},
    "leather_main_droite": {"attack": 5, "dodge": 1},
    "leather_dagger": {"attack": 5, "dodge": 2},
    "leather_greatsword": {"attack": 13, "dodge": 3, "defense": -2},
    "linen_main_droite": {"attack": 4, "crit_damage": 5, "dodge": 1},
    "linen_rapier": {"attack": 5, "crit_chance": 3, "speed": 1},
    "linen_greatblade": {"attack": 12, "crit_damage": 10, "crit_chance": 3, "defense": -3, "dodge": -1},
}
# Boucliers (1 main) : défense + thème. (2 mains) : ~2.2× + malus.
SHIELD_STATS = {
    "wooden_shield": {"defense": 5, "max_hp": 6},
    "iron_buckler": {"defense": 6, "dodge": 2},
    "iron_warshield": {"defense": 6, "max_hp": 8},
    "iron_tower_shield": {"defense": 15, "dodge": 5, "attack": -4, "speed": -2},
    "slime_shield": {"defense": 5, "max_hp": 8},
    "slime_buckler": {"defense": 4, "hp_regeneration": 3, "max_hp": 4},
    "slime_tower_shield": {"defense": 13, "max_hp": 20, "attack": -5},
    "gobelin_main_gauche": {"defense": 5, "crit_chance": 2},
    "gobelin_buckler": {"defense": 6, "crit_chance": 2},
    "gobelin_warshield": {"defense": 13, "crit_chance": 4, "attack": -5, "crit_damage": -4},
    "leather_main_gauche": {"defense": 4, "dodge": 2},
    "leather_buckler": {"defense": 4, "max_hp": 5},
    "leather_tower_shield": {"defense": 11, "dodge": 4, "attack": -3},
    "linen_main_gauche": {"defense": 3, "crit_damage": 3, "dodge": 1},
    "linen_aegis": {"defense": 4, "dodge": 2, "crit_damage": 2},
    "linen_tower_shield": {"dodge": 6, "defense": 6, "crit_damage": -2},
}
# Équipements gobelin/slime (hors armes/boucliers), par slot.
GOBELIN_EQUIP = {
    "casque": {"defense": 2, "max_hp": 6, "crit_chance": 3},
    "plastron": {"attack": 4, "crit_chance": 2, "max_hp": 4},
    "jambieres": {"attack": 3, "crit_chance": 2},
    "bottes": {"attack": 2, "crit_chance": 1, "speed": 1},
    "collier": {"attack": 3, "crit_chance": 2},
    "bracelet": {"attack": 3, "crit_chance": 1},
    "bague": {"crit_chance": 3, "crit_damage": 6},
    "ceinture": {"attack": 3, "crit_chance": 1},
    "cape": {"attack": 2, "crit_chance": 2},
    "boucle_oreille": {"attack": 2, "crit_chance": 2},
}
SLIME_EQUIP = {
    "casque": {"max_hp": 8, "hp_regeneration": 1, "defense": 1},
    "plastron": {"max_hp": 10, "hp_regeneration": 1, "defense": 1},
    "jambieres": {"max_hp": 8, "hp_regeneration": 1},
    "bottes": {"max_hp": 6, "hp_regeneration": 1},
    "collier": {"max_hp": 10, "hp_regeneration": 2},
    "bracelet": {"max_hp": 6, "hp_regeneration": 1},
    "bague": {"max_hp": 6, "hp_regeneration": 2},
    "ceinture": {"max_hp": 6, "hp_regeneration": 1},
    "cape": {"max_hp": 8, "defense": 2},
    "boucle_oreille": {"max_hp": 6, "hp_regeneration": 1},
}


def plus_stats(sb: dict | None) -> dict:
    """Stats du '+' : positifs ×1.5 (arrondi sup), négatifs conservés."""
    out = {}
    for k, v in (sb or {}).items():
        out[k] = math.ceil(v * 1.5) if v > 0 else v
    return out


def main() -> None:
    items = _load(ITEMS)
    by_code = {i["code"]: i for i in items}

    def ensure_item(entry):
        if entry["code"] in by_code:
            by_code[entry["code"]].update(entry)
        else:
            items.append(entry)
            by_code[entry["code"]] = entry

    def resource(code, name, desc, rarity, buy_price=None):
        ensure_item({
            "code": code, "name": name, "description": desc,
            "category": "resource", "rarity": rarity, "stackable": True,
            "max_stack": None, "sell_price": 0, "buy_price": buy_price,
            "icon": None, "stat_bonuses": None, "equipment_slot": None,
            "requires_two_hands": False, "family": "",
        })

    # 1. Ressources
    resource("sang_gobelin_hq", "Sang de gobelin de haute qualité",
             "Sang rare prélevé sur les gobelins d'élite. Infuse l'équipement gobelin.",
             "rare")
    resource("sang_slime", "Sang de slime",
             "Essence visqueuse rare distillée des slimes. Infuse l'équipement slime.",
             "rare")
    resource("infuseur", "Infuseur",
             "Catalyseur d'infusion. Permet d'améliorer un équipement de panoplie. Achetable en boutique.",
             "uncommon", buy_price=1000)

    # 2. Rééquilibrage armes/boucliers
    for code, sb in {**WEAPON_STATS, **SHIELD_STATS}.items():
        if code in by_code:
            by_code[code]["stat_bonuses"] = sb

    # 3. Rééquilibrage équipements gobelin/slime (hors armes/boucliers)
    for it in items:
        if it.get("category") in ("weapon", "shield"):
            continue
        fam, slot = it.get("family"), it.get("equipment_slot")
        if fam == "gobelin" and slot in GOBELIN_EQUIP:
            it["stat_bonuses"] = dict(GOBELIN_EQUIP[slot])
        elif fam == "slime" and slot in SLIME_EQUIP:
            it["stat_bonuses"] = dict(SLIME_EQUIP[slot])

    # 4. Versions "+" (gobelin_plus / slime_plus) + recettes
    plus_recipes = []
    for fam, sang in [("gobelin", "sang_gobelin_hq"), ("slime", "sang_slime")]:
        base_items = [i for i in list(items) if i.get("family") == fam]
        for base in base_items:
            pcode = base["code"] + "_plus"
            ensure_item({
                **base,
                "code": pcode,
                "name": base["name"] + " +",
                "description": base["description"] + " — version infusée (améliorée).",
                "rarity": _RARITY_UP.get(base.get("rarity", "common"), "rare"),
                "family": fam + "_plus",
                "stat_bonuses": plus_stats(base.get("stat_bonuses")),
                "sell_price": int((base.get("sell_price") or 0) * 2),
            })
            plus_recipes.append({
                "code": pcode + "_recipe",
                "name": base["name"] + " +",
                "result_item_code": pcode,
                "result_quantity": 1,
                "ingredients": [
                    {"item_code": base["code"], "quantity": 1},
                    {"item_code": sang, "quantity": 1},
                    {"item_code": "infuseur", "quantity": 1},
                ],
            })

    _save(ITEMS, items)

    # 5. Recettes : retire les anciennes "+_recipe", ajoute les nouvelles
    crafts = _load(CRAFTS)
    crafts = [r for r in crafts if not r["code"].endswith("_plus_recipe")]
    crafts += plus_recipes
    _save(CRAFTS, crafts)

    # 6. Bonus de panoplie "+" (légèrement supérieurs au base)
    sets = _load(SETS)
    sets["gobelin_plus"] = {
        "name": "Gobeline +", "description": "Panoplie gobeline infusée — frappe critique renforcée.",
        "icon": "👹", "color": "#9bd96a",
        "tiers": [
            {"min_pieces": 2, "type": "crit_damage_flat", "value": 2},
            {"min_pieces": 4, "type": "crit_damage_flat", "value": 4},
            {"min_pieces": 8, "type": "crit_damage_flat", "value": 7},
            {"min_pieces": 12, "type": "crit_damage_flat", "value": 12},
        ],
    }
    sets["slime_plus"] = {
        "name": "Slime +", "description": "Panoplie slime infusée — régénération renforcée.",
        "icon": "🟢", "color": "#a7f084",
        "tiers": [
            {"min_pieces": 2, "type": "hp_regeneration_flat", "value": 2},
            {"min_pieces": 4, "type": "hp_regeneration_flat", "value": 4},
            {"min_pieces": 8, "type": "hp_regeneration_flat", "value": 8},
            {"min_pieces": 12, "type": "hp_regeneration_flat", "value": 12},
        ],
    }
    _save(SETS, sets)

    # 7. Infuseur au shop (1000 or)
    shop = _load(SHOP)
    if not any(s["item_code"] == "infuseur" for s in shop):
        shop.append({
            "item_code": "infuseur", "buy_price": 1000,
            "max_sell_price": 0, "min_sell_price": 0,
            "stock_threshold": 100, "enabled": True,
        })
    _save(SHOP, shop)

    # 8. Drops rares (0 ou 1, ~5× plus rares qu'une dent à 0.75 → 0.15)
    mobs = _load(MOBS)
    mob_by = {m["code"]: m for m in mobs}

    def add_drop(mob_code, item_code, rate):
        m = mob_by.get(mob_code)
        if not m:
            return
        lt = [e for e in (m.get("loot_table") or []) if e.get("item_code") != item_code]
        lt.append({"item_code": item_code, "drop_rate": rate,
                   "min_quantity": 1, "max_quantity": 1})
        m["loot_table"] = lt

    add_drop("gobelin_superieur", "sang_gobelin_hq", 0.15)
    add_drop("gobelin_assassin", "sang_gobelin_hq", 0.15)
    add_drop("slime", "sang_slime", 0.15)
    _save(MOBS, mobs)

    n_plus = sum(1 for i in items if str(i.get("family", "")).endswith("_plus"))
    print(f"✅ {len(WEAPON_STATS)} armes + {len(SHIELD_STATS)} boucliers rééquilibrés")
    print(f"✅ {n_plus} items '+' générés, {len(plus_recipes)} recettes")
    print("✅ ressources (sang gobelin/slime, infuseur) + drops + shop + sets")


if __name__ == "__main__":
    main()
