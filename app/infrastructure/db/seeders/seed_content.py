import json
from pathlib import Path

from app.infrastructure.db.repositories.item_repository import ItemRepository
from app.infrastructure.db.repositories.mob_repository import MobRepository
from app.infrastructure.db.repositories.class_repository import ClassRepository
from app.infrastructure.db.session import get_db_session


BASE_DIR = Path(__file__).resolve().parents[2]
CONTENT_DIR = BASE_DIR / "content"


def load_json(filename: str) -> list[dict]:
    filepath = CONTENT_DIR / filename
    with filepath.open("r", encoding="utf-8") as file:
        return json.load(file)


def seed_items() -> None:
    items = load_json("items.json")

    with get_db_session() as session:
        item_repository = ItemRepository(session)

        for item_data in items:
            existing = item_repository.get_by_code(item_data["code"])
            if existing is not None:
                continue

            item_repository.create(
                code=item_data["code"],
                name=item_data["name"],
                description=item_data["description"],
                category=item_data["category"],
                rarity=item_data["rarity"],
                stackable=item_data["stackable"],
                max_stack=item_data["max_stack"],
                sell_price=item_data["sell_price"],
                buy_price=item_data["buy_price"],
                icon=item_data["icon"],
                stat_bonuses=item_data["stat_bonuses"],
            )

    print("Items seedés.")


def seed_mobs() -> None:
    mobs = load_json("mobs.json")

    with get_db_session() as session:
        mob_repository = MobRepository(session)

        for mob_data in mobs:
            existing = mob_repository.get_by_code(mob_data["code"])
            if existing is not None:
                continue

            mob_repository.create(
                code=mob_data["code"],
                name=mob_data["name"],
                description=mob_data["description"],
                max_hp=mob_data["max_hp"],
                attack=mob_data["attack"],
                defense=mob_data["defense"],
                xp_reward=mob_data["xp_reward"],
                gold_reward=mob_data["gold_reward"],
                loot_table=mob_data["loot_table"],
            )

    print("Mobs seedés.")

def seed_classes() -> None:
    classes = load_json("classes.json")

    with get_db_session() as session:
        class_repository = ClassRepository(session)

        for class_data in classes:
            existing = class_repository.get_by_code(class_data["code"])
            if existing is not None:
                continue

            class_repository.create(
                code=class_data["code"],
                name=class_data["name"],
                description=class_data["description"],
                stat_bonuses=class_data["stat_bonuses"],
            )

    print("Classes seedées.")

def main() -> None:
    seed_items()
    seed_mobs()
    seed_classes()
    print("Seed terminé.")


if __name__ == "__main__":
    main()