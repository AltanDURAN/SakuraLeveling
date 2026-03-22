from app.domain.value_objects.stats import Stats
from app.domain.entities.player_profile import PlayerProfile
from app.domain.entities.player_equipment_item import PlayerEquipmentItem


class StatsService:
    def calculate_player_stats(
        self,
        profile: PlayerProfile,
        equipped_items: list[PlayerEquipmentItem],
    ) -> Stats:
        level = profile.progression.level

        max_hp = 100 + (level - 1) * 10
        attack = 10 + (level - 1) * 2
        defense = 5 + (level - 1) * 1

        for equipment_item in equipped_items:
            bonuses = equipment_item.item_definition.stat_bonuses or {}

            max_hp += int(bonuses.get("max_hp", 0))
            attack += int(bonuses.get("attack", 0))
            defense += int(bonuses.get("defense", 0))

        return Stats(
            max_hp=max_hp,
            attack=attack,
            defense=defense,
        )