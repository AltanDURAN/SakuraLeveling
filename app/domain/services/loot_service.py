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

        `family_drops` : mapping famille → {item_code, mobs:{code:{min,max}}}.
        Si fourni et que la famille du mob y figure, on ajoute le drop de
        famille — GARANTI (pas de roll de rareté), quantité tirée dans le
        [min,max] PROPRE à ce monstre (défaut 1/1 si non défini). Le
        `drop_rate_multiplier` ne s'applique PAS (drop garanti).
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

        # 2. Drop de famille GARANTI (quantité min/max propre au mob).
        if family_drops and mob.family:
            cfg = family_drops.get(mob.family)
            if cfg and cfg.get("item_code"):
                entry = (cfg.get("mobs") or {}).get(mob.code) or {}
                lo = max(0, int(entry.get("min", 1)))
                hi = max(lo, int(entry.get("max", lo if lo else 1)))
                if hi > 0:
                    quantity = random.randint(lo, hi)
                    if quantity > 0:
                        dropped_items.append((cfg["item_code"], quantity))

        return dropped_items
