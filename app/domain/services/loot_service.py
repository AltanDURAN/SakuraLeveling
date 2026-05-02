import random

from app.domain.entities.mob_definition import MobDefinition


class LootService:
    def generate_loot(
        self,
        mob: MobDefinition,
        drop_rate_multiplier: float = 1.0,
    ) -> list[tuple[str, int]]:
        """Roll les drops d'un mob.

        `drop_rate_multiplier` est appliqué de manière MULTIPLICATIVE sur le
        drop_rate de chaque entrée (ex : 1.10 = +10%). Cela préserve la rareté
        des items rares (un drop à 1% × 1.10 = 1.1%, pas 11%).
        """
        if not mob.loot_table:
            return []

        dropped_items: list[tuple[str, int]] = []

        for entry in mob.loot_table:
            item_code = entry["item_code"]
            base_rate = float(entry["drop_rate"])
            min_quantity = int(entry.get("min_quantity", 1))
            max_quantity = int(entry.get("max_quantity", 1))

            effective_rate = max(0.0, min(1.0, base_rate * drop_rate_multiplier))

            if random.random() <= effective_rate:
                quantity = random.randint(min_quantity, max_quantity)
                dropped_items.append((item_code, quantity))

        return dropped_items
