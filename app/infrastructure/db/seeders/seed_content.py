import json
from pathlib import Path

from app.infrastructure.db.models.profession_model import ProfessionDefinitionModel
from app.infrastructure.db.repositories.class_repository import ClassRepository
from app.infrastructure.db.repositories.craft_repository import CraftRepository
from app.infrastructure.db.repositories.item_repository import ItemRepository
from app.infrastructure.db.repositories.mob_repository import MobRepository
from app.infrastructure.db.repositories.profession_repository import ProfessionRepository
from app.infrastructure.db.repositories.quest_repository import QuestRepository
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

            if existing is None:
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
            else:
                item_repository.update_by_code(
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

            payload = dict(
                code=mob_data["code"],
                name=mob_data["name"],
                description=mob_data["description"],
                max_hp=mob_data["max_hp"],
                current_hp=mob_data.get("current_hp", mob_data["max_hp"]),
                attack=mob_data["attack"],
                defense=mob_data["defense"],
                speed=mob_data["speed"],
                crit_chance=mob_data["crit_chance"],
                crit_damage=mob_data["crit_damage"],
                dodge=mob_data["dodge"],
                hp_regeneration=mob_data["hp_regeneration"],
                xp_reward=mob_data["xp_reward"],
                gold_reward=mob_data["gold_reward"],
                image_name=mob_data.get("image_name"),
                spawn_weight=mob_data.get("spawn_weight", 1),
                loot_table=mob_data["loot_table"],
            )

            if existing is None:
                mob_repository.create(**payload)
            else:
                mob_repository.update_by_code(**payload)

    print("Mobs seedés.")


def seed_classes() -> None:
    classes = load_json("classes.json")

    with get_db_session() as session:
        class_repository = ClassRepository(session)

        for class_data in classes:
            existing = class_repository.get_by_code(class_data["code"])

            if existing is None:
                class_repository.create(
                    code=class_data["code"],
                    name=class_data["name"],
                    description=class_data["description"],
                    stat_bonuses=class_data["stat_bonuses"],
                    unlock_requirements=class_data.get("unlock_requirements"),
                )
            else:
                class_repository.update_by_code(
                    code=class_data["code"],
                    name=class_data["name"],
                    description=class_data["description"],
                    stat_bonuses=class_data["stat_bonuses"],
                    unlock_requirements=class_data.get("unlock_requirements"),
                )

    print("Classes seedées.")


def seed_crafts() -> None:
    crafts = load_json("crafts.json")

    with get_db_session() as session:
        craft_repository = CraftRepository(session)
        item_repository = ItemRepository(session)

        for craft_data in crafts:
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

            existing = craft_repository.get_by_code(craft_data["code"])

            if existing is None:
                craft_repository.create(
                    code=craft_data["code"],
                    name=craft_data["name"],
                    result_item_definition_id=result_item.id,
                    result_quantity=craft_data["result_quantity"],
                    ingredients=ingredients,
                )
            else:
                craft_repository.update_by_code(
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

            if existing is None:
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
            else:
                quest_repository.update_definition_by_code(
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


def seed_professions() -> None:
    professions = load_json("professions.json")

    with get_db_session() as session:
        repo = ProfessionRepository(session)

        for profession_data in professions:
            existing = repo.get_definition_by_code(profession_data["code"])

            if existing is None:
                session.add(
                    ProfessionDefinitionModel(
                        code=profession_data["code"],
                        name=profession_data["name"],
                        description=profession_data["description"],
                    )
                )
            else:
                model = session.get(ProfessionDefinitionModel, existing.id)
                if model is None:
                    continue

                model.name = profession_data["name"]
                model.description = profession_data["description"]

        session.commit()

    print("Professions seedées.")


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