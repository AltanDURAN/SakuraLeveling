import random

from app.domain.entities.mob_definition import MobDefinition


class LootService:
    def generate_loot(self, mob: MobDefinition) -> list[tuple[str, int]]:
        if not mob.loot_table:
            return []

        dropped_items: list[tuple[str, int]] = []

        for entry in mob.loot_table:
            item_code = entry["item_code"]
            drop_rate = float(entry["drop_rate"])
            min_quantity = int(entry.get("min_quantity", 1))
            max_quantity = int(entry.get("max_quantity", 1))

            if random.random() <= drop_rate:
                quantity = random.randint(min_quantity, max_quantity)
                dropped_items.append((item_code, quantity))

        return dropped_items