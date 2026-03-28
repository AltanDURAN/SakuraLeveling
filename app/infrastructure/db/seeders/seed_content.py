import json
from pathlib import Path

from app.infrastructure.db.repositories.item_repository import ItemRepository
from app.infrastructure.db.repositories.mob_repository import MobRepository
from app.infrastructure.db.repositories.class_repository import ClassRepository
from app.infrastructure.db.repositories.craft_repository import CraftRepository
from app.infrastructure.db.repositories.quest_repository import QuestRepository
from app.infrastructure.db.repositories.profession_repository import ProfessionRepository
from app.infrastructure.db.models.profession_model import ProfessionDefinitionModel
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
    
def seed_crafts() -> None:
    crafts = load_json("crafts.json")

    with get_db_session() as session:
        craft_repository = CraftRepository(session)
        item_repository = ItemRepository(session)

        for craft_data in crafts:
            existing = craft_repository.get_by_code(craft_data["code"])
            if existing is not None:
                continue

            result_item = item_repository.get_by_code(craft_data["result_item_code"])
            if result_item is None:
                continue

            ingredients: list[tuple[int, int]] = []
            valid = True

            for ingredient_data in craft_data["ingredients"]:
                ingredient_item = item_repository.get_by_code(ingredient_data["item_code"])
                if ingredient_item is None:
                    valid = False
                    break

                ingredients.append((ingredient_item.id, ingredient_data["quantity"]))

            if not valid:
                continue

            craft_repository.create(
                code=craft_data["code"],
                name=craft_data["name"],
                result_item_definition_id=result_item.id,
                result_quantity=craft_data["result_quantity"],
                ingredients=ingredients,
            )

    print("Crafts seedés.")
    
def seed_quests() -> None:
    quests = load_json("quests.json")

    with get_db_session() as session:
        quest_repository = QuestRepository(session)

        for quest_data in quests:
            existing = quest_repository.get_definition_by_code(quest_data["code"])
            if existing is not None:
                continue

            quest_repository.create_definition(
                code=quest_data["code"],
                name=quest_data["name"],
                description=quest_data["description"],
                objective_type=quest_data["objective_type"],
                target_code=quest_data["target_code"],
                required_quantity=quest_data["required_quantity"],
                reward_gold=quest_data["reward_gold"],
                reward_xp=quest_data["reward_xp"],
                reward_items=quest_data["reward_items"],
            )

    print("Quêtes seedées.")

def seed_professions():
    professions = load_json("professions.json")

    with get_db_session() as session:
        repo = ProfessionRepository(session)

        for p in professions:
            if repo.get_definition_by_code(p["code"]):
                continue

            session.add(
                ProfessionDefinitionModel(
                    code=p["code"],
                    name=p["name"],
                    description=p["description"],
                )
            )

        session.commit()

def main() -> None:
    seed_items()
    seed_mobs()
    seed_classes()
    seed_crafts()
    seed_quests()
    seed_professions()
    print("Seed terminé.")


if __name__ == "__main__":
    main()