"""Synchronisation des éditions admin vers les JSON de contenu (source du seed).

Quand un item (ou autre contenu) est créé/édité via l'admin web, il est écrit
en DB (live immédiat) MAIS la DB peut être reconstruite depuis les JSON
(`seed_content`). Pour que « repop de la base » ne perde rien, on réécrit aussi
l'entrée dans le JSON correspondant.

Phase 2 (git) : `git_sync.push_content` versionne ces JSON hors-VPS.
"""

from __future__ import annotations

import logging

from webapp.admin import json_writer

_logger = logging.getLogger(__name__)

# Champs d'un item dans items.json (ordre/schéma du seed).
ITEM_FIELDS = (
    "code", "name", "description", "category", "rarity", "stackable",
    "max_stack", "sell_price", "buy_price", "icon", "stat_bonuses",
    "equipment_slot", "requires_two_hands", "family",
)


def build_item_dict(
    *, code, name, description, category, rarity, stackable, max_stack,
    sell_price, buy_price, icon, stat_bonuses, equipment_slot,
    requires_two_hands, family,
) -> dict:
    """Construit le dict d'un item au schéma exact d'items.json."""
    return {
        "code": code,
        "name": name,
        "description": description or "",
        "category": category,
        "rarity": rarity or "common",
        "stackable": bool(stackable),
        "max_stack": max_stack,
        "sell_price": sell_price or 0,
        "buy_price": buy_price,
        "icon": icon,
        "stat_bonuses": stat_bonuses or None,
        "equipment_slot": equipment_slot,
        "requires_two_hands": bool(requires_two_hands),
        "family": family or "",
    }


def delete_item_json(code: str) -> list[str]:
    """Retire l'item `code` de TOUS les JSON de contenu qui le référencent :
    items.json, shop_items.json, crafts.json (recettes le produisant + lignes
    d'ingrédient le citant), mobs.json (loot_table), family_drops.json.
    Retourne la liste des fichiers modifiés (pour le git push)."""
    touched: list[str] = []

    def _save(name, data):
        json_writer.atomic_write_json(name, data)
        touched.append(name)

    # items.json
    items = json_writer.load_json("items.json", default=[]) or []
    new_items = [it for it in items if it.get("code") != code]
    if len(new_items) != len(items):
        _save("items.json", new_items)

    # shop_items.json
    shop = json_writer.load_json("shop_items.json", default=[]) or []
    new_shop = [s for s in shop if s.get("item_code") != code]
    if len(new_shop) != len(shop):
        _save("shop_items.json", new_shop)

    # crafts.json : retire les recettes produisant l'item + les ingrédients le citant
    crafts = json_writer.load_json("crafts.json", default=[]) or []
    new_crafts = []
    crafts_changed = False
    for r in crafts:
        if r.get("result_item_code") == code:
            crafts_changed = True
            continue  # recette produisant l'item supprimé → drop
        ings = r.get("ingredients") or []
        kept = [i for i in ings if i.get("item_code") != code]
        if len(kept) != len(ings):
            r = {**r, "ingredients": kept}
            crafts_changed = True
        new_crafts.append(r)
    if crafts_changed:
        _save("crafts.json", new_crafts)

    # mobs.json : retire l'item des loot_table
    mobs = json_writer.load_json("mobs.json", default=[]) or []
    mobs_changed = False
    for m in mobs:
        lt = m.get("loot_table") or []
        kept = [e for e in lt if e.get("item_code") != code]
        if len(kept) != len(lt):
            m["loot_table"] = kept
            mobs_changed = True
    if mobs_changed:
        _save("mobs.json", mobs)

    # family_drops.json : retire les familles dont le drop commun est cet item
    fdrops = json_writer.load_json("family_drops.json", default={}) or {}
    if isinstance(fdrops, dict):
        new_fd = {k: v for k, v in fdrops.items()
                  if not (isinstance(v, dict) and v.get("item_code") == code)}
        if len(new_fd) != len(fdrops):
            _save("family_drops.json", new_fd)

    return touched


def build_mob_dict(
    *, code, name, family, description, max_hp, current_hp, attack, defense,
    crit_chance, crit_damage, dodge, hp_regeneration, speed, xp_reward,
    gold_reward, spawn_weight, loot_table, image_name, element,
) -> dict:
    """Construit le dict d'un mob au schéma exact de mobs.json (ordre du seed)."""
    return {
        "code": code,
        "name": name,
        "family": family or "unknown",
        "description": description or "",
        "max_hp": int(max_hp),
        "current_hp": int(current_hp if current_hp is not None else max_hp),
        "attack": int(attack),
        "defense": int(defense),
        "crit_chance": int(crit_chance),
        "crit_damage": int(crit_damage),
        "dodge": int(dodge),
        "hp_regeneration": int(hp_regeneration),
        "speed": int(speed),
        "xp_reward": int(xp_reward),
        "gold_reward": int(gold_reward),
        "spawn_weight": int(spawn_weight),
        "loot_table": loot_table or [],
        "image_name": image_name,
        "element": element or "",
    }


def upsert_mob_json(mob: dict) -> None:
    """Insère ou met à jour le mob (par `code`) dans mobs.json. Best-effort :
    une erreur d'écriture ne casse pas l'action admin (la DB reste la source
    live ; le JSON sert au reseed → reseed-safe comme les items)."""
    try:
        data = json_writer.load_json("mobs.json", default=[]) or []
        code = mob["code"]
        for i, entry in enumerate(data):
            if isinstance(entry, dict) and entry.get("code") == code:
                data[i] = mob
                break
        else:
            data.append(mob)
        json_writer.atomic_write_json("mobs.json", data)
        _logger.info("mobs.json synchronisé pour '%s'", code)
    except Exception:
        _logger.warning("Échec sync mobs.json pour '%s'", mob.get("code"), exc_info=True)


def load_farm_zones() -> dict:
    return json_writer.load_json("farm_zones.json", default={}) or {}


def build_zone_dict(
    *, name, channel_id, families, background, essences_min, essences_max,
) -> dict:
    """Construit une entrée de zone au schéma zone-centré de farm_zones.json."""
    lo = max(0, int(essences_min or 0))
    hi = max(lo, int(essences_max or 0))
    if isinstance(families, str):
        families = families.replace(",", " ").split()
    return {
        "name": name or "",
        "channel_id": int(channel_id or 0),
        "families": [f.strip() for f in (families or []) if f and f.strip()],
        "background": background or "",
        "essences_min": lo,
        "essences_max": hi,
    }


def _zones_as_list(data: dict) -> list[dict]:
    """Renvoie la liste `zones` de farm_zones.json (migre l'ancien format dict
    vers une liste au passage)."""
    zones = data.get("zones")
    if isinstance(zones, list):
        return zones
    # Ancien format {famille: {...}} → normalise via le loader.
    from app.infrastructure.encounters import farm_zone_loader
    farm_zone_loader.clear_cache()
    return [dict(z) for z in farm_zone_loader.list_zones()]


def upsert_zone_json(zone: dict, original_channel_id: int | None = None) -> None:
    """Insère/met à jour une zone dans farm_zones.json (clé = channel_id).
    `original_channel_id` : channel_id AVANT édition (permet de changer le
    channel d'une zone existante)."""
    data = load_farm_zones()
    zones = _zones_as_list(data)
    key = original_channel_id if original_channel_id is not None else zone["channel_id"]
    for i, z in enumerate(zones):
        if isinstance(z, dict) and int(z.get("channel_id", 0) or 0) == int(key or 0):
            zones[i] = zone
            break
    else:
        zones.append(zone)
    data["zones"] = zones
    json_writer.atomic_write_json("farm_zones.json", data)


def delete_zone_json(channel_id: int) -> None:
    data = load_farm_zones()
    zones = _zones_as_list(data)
    data["zones"] = [
        z for z in zones
        if int((z or {}).get("channel_id", 0) or 0) != int(channel_id or 0)
    ]
    json_writer.atomic_write_json("farm_zones.json", data)


def delete_mob_json(code: str) -> list[str]:
    """Retire le mob `code` de mobs.json. Retourne les fichiers modifiés."""
    mobs = json_writer.load_json("mobs.json", default=[]) or []
    new_mobs = [m for m in mobs if m.get("code") != code]
    if len(new_mobs) != len(mobs):
        json_writer.atomic_write_json("mobs.json", new_mobs)
        return ["mobs.json"]
    return []


def upsert_item_json(item: dict) -> None:
    """Insère ou met à jour l'item (par `code`) dans items.json.
    Best-effort : une erreur d'écriture JSON ne doit pas casser l'action admin
    (la DB reste la source live ; le JSON sert au reseed)."""
    try:
        data = json_writer.load_json("items.json", default=[]) or []
        code = item["code"]
        for i, entry in enumerate(data):
            if isinstance(entry, dict) and entry.get("code") == code:
                data[i] = item
                break
        else:
            data.append(item)
        json_writer.atomic_write_json("items.json", data)
        _logger.info("items.json synchronisé pour '%s'", code)
    except Exception:
        _logger.warning("Échec sync items.json pour '%s'", item.get("code"), exc_info=True)
