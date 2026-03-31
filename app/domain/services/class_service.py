from app.domain.entities.class_definition import ClassDefinition
from app.domain.entities.player_inventory_item import PlayerInventoryItem
from app.domain.entities.player_profession import PlayerProfession


class ClassService:
    def can_unlock_class(
        self,
        class_definition: ClassDefinition,
        player_professions: list[tuple[str, PlayerProfession]],
        inventory_items: list[PlayerInventoryItem],
    ) -> bool:
        requirements = class_definition.unlock_requirements or []
        if not requirements:
            return True

        profession_map = {
            profession_code: profession
            for profession_code, profession in player_professions
        }

        inventory_map = {
            item.item_definition.code: item.quantity
            for item in inventory_items
        }

        for requirement in requirements:
            requirement_type = requirement.get("type")

            if requirement_type == "profession_level":
                profession_code = requirement["profession_code"]
                required_level = requirement["level"]

                player_profession = profession_map.get(profession_code)
                if player_profession is None or player_profession.level < required_level:
                    return False

            elif requirement_type == "has_item":
                item_code = requirement["item_code"]
                required_quantity = requirement["quantity"]

                if inventory_map.get(item_code, 0) < required_quantity:
                    return False

            else:
                return False

        return True