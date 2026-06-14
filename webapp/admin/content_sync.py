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
