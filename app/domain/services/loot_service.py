import random

from app.domain.entities.mob_definition import MobDefinition


class LootService:
    def generate_loot(
        self,
        mob: MobDefinition,
        drop_rate_multiplier: float = 1.0,
        family_drops: dict | None = None,
    ) -> list[tuple[str, int]]:
        """Roll les drops d'un mob.

        `drop_rate_multiplier` est appliqué de manière MULTIPLICATIVE sur le
        drop_rate de chaque entrée (ex : 1.10 = +10%). Cela préserve la rareté
        des items rares (un drop à 1% × 1.10 = 1.1%, pas 11%).

        `family_drops` : mapping famille → {item_code, drop_rate}. Si fourni et
        que la famille du mob y figure, on roll EN PLUS le drop commun de
        famille (≥1 par famille). Sa quantité croît avec la puissance du mob
        (proxy : xp_reward) — un mob faible lâche 1 ressource, un mob fort 1-N.
        """
        dropped_items: list[tuple[str, int]] = []

        # 1. Loot spécifique du mob (drops rares propres, autorés au cas par cas).
        for entry in mob.loot_table or []:
            item_code = entry["item_code"]
            base_rate = float(entry["drop_rate"])
            min_quantity = int(entry.get("min_quantity", 1))
            max_quantity = int(entry.get("max_quantity", 1))

            effective_rate = max(0.0, min(1.0, base_rate * drop_rate_multiplier))

            if random.random() <= effective_rate:
                quantity = random.randint(min_quantity, max_quantity)
                dropped_items.append((item_code, quantity))

        # 2. Drop commun de famille (quantité ∝ puissance du mob).
        if family_drops and mob.family:
            cfg = family_drops.get(mob.family)
            if cfg:
                rate = max(0.0, min(1.0, float(cfg["drop_rate"]) * drop_rate_multiplier))
                if random.random() <= rate:
                    qty_max = max(1, round(mob.xp_reward / 80))
                    quantity = random.randint(1, qty_max)
                    dropped_items.append((cfg["item_code"], quantity))

        return dropped_items
