"""Migration vers le système d'équipement SIMPLIFIÉ (7 emplacements).

Ancien système : 12 emplacements (casque, plastron, jambières, bottes,
main droite, main gauche, collier, bracelet, bague, ceinture, cape, boucle
d'oreille) et autant de catégories d'items.

Nouveau : 4 types d'items (tete, corps, accessoire, arme) répartis sur
7 emplacements — tête ×1, corps ×1, accessoire ×3, arme/bouclier ×2.

Ce script :
  1. convertit les CATÉGORIES et les emplacements des items (JSON + base) ;
  2. DÉSÉQUIPE tout le monde et rend les pièces à l'inventaire — décision
     produit : aucune perte, chacun se rééquipe avec le nouveau système.

Usage : .venv/bin/python -m scripts.migrate_equipment_system [--write]
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

from app.shared.enums import LEGACY_CATEGORY_MAP, LEGACY_SLOT_MAP

CONTENT = Path(__file__).resolve().parents[1] / "app/infrastructure/content"


def migrate_items_json(write: bool) -> Counter:
    path = CONTENT / "items.json"
    items = json.loads(path.read_text(encoding="utf-8"))
    stats = Counter()
    for item in items:
        old_cat = item.get("category")
        if old_cat in LEGACY_CATEGORY_MAP:
            item["category"] = LEGACY_CATEGORY_MAP[old_cat]
            stats[f"catégorie {old_cat} → {item['category']}"] += 1
        old_slot = item.get("equipment_slot")
        if old_slot in LEGACY_SLOT_MAP:
            item["equipment_slot"] = LEGACY_SLOT_MAP[old_slot]
            stats["emplacement converti"] += 1
    if write:
        path.write_text(json.dumps(items, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
    return stats


def migrate_database(write: bool) -> dict:
    """Convertit les items en base et rend l'équipement porté à l'inventaire."""
    # Enregistre TOUS les modèles avant d'ouvrir une session : sans ça,
    # SQLAlchemy ne résout pas les clés étrangères (NoReferencedTableError)
    # quand le script tourne seul, hors du bot ou de la webapp.
    import importlib
    import pkgutil

    import app.infrastructure.db.models as _models_pkg
    for _m in pkgutil.iter_modules(_models_pkg.__path__):
        importlib.import_module(f"{_models_pkg.__name__}.{_m.name}")
    from sqlalchemy import delete, select

    from app.infrastructure.db.models.equipment_model import PlayerEquipmentItemModel
    from app.infrastructure.db.models.item_model import ItemDefinitionModel
    from app.infrastructure.db.repositories.inventory_repository import (
        InventoryRepository,
    )
    from app.infrastructure.db.session import get_db_session

    report = {"items_convertis": 0, "pieces_rendues": 0, "joueurs_touches": 0}
    with get_db_session() as session:
        for model in session.execute(select(ItemDefinitionModel)).scalars().all():
            changed = False
            if model.category in LEGACY_CATEGORY_MAP:
                model.category = LEGACY_CATEGORY_MAP[model.category]
                changed = True
            if model.equipment_slot in LEGACY_SLOT_MAP:
                model.equipment_slot = LEGACY_SLOT_MAP[model.equipment_slot]
                changed = True
            if changed:
                report["items_convertis"] += 1

        worn = session.execute(select(PlayerEquipmentItemModel)).scalars().all()
        players = set()
        inventory = InventoryRepository(session)
        for row in worn:
            players.add(row.player_id)
            inventory.add_item(row.player_id, row.item_definition_id, 1)
            report["pieces_rendues"] += 1
        report["joueurs_touches"] = len(players)

        if write:
            session.execute(delete(PlayerEquipmentItemModel))
            session.commit()
        else:
            session.rollback()
    return report


def main() -> None:
    write = "--write" in sys.argv
    print("— Contenu (items.json) —")
    for label, n in migrate_items_json(write).most_common():
        print(f"    {label} : {n}")
    print("— Base de données —")
    for k, v in migrate_database(write).items():
        print(f"    {k} : {v}")
    print("\n✅ appliqué" if write else "\n(dry-run — relancer avec --write)")


if __name__ == "__main__":
    main()
