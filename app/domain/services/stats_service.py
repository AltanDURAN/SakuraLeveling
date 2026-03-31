from app.domain.entities.class_definition import ClassDefinition
from app.domain.entities.player_equipment_item import PlayerEquipmentItem
from app.domain.entities.player_profile import PlayerProfile
from app.domain.value_objects.stats import Stats


class StatsService:
    def calculate_player_stats(
        self,
        profile: PlayerProfile,
        equipped_items: list[PlayerEquipmentItem],
        active_class: ClassDefinition | None = None,
    ) -> Stats:
        level = profile.progression.level

        max_hp = 100 + (level - 1) * 10
        attack = 10 + (level - 1) * 2
        defense = 5 + (level - 1) * 1

        crit_chance = 0.05
        crit_damage = 1.50
        dodge = 0.00

        if active_class is not None:
            bonuses = active_class.stat_bonuses or {}
            max_hp += int(bonuses.get("max_hp", 0))
            attack += int(bonuses.get("attack", 0))
            defense += int(bonuses.get("defense", 0))
            crit_chance += float(bonuses.get("crit_chance", 0.0))
            crit_damage += float(bonuses.get("crit_damage", 0.0))
            dodge += float(bonuses.get("dodge", 0.0))

        for equipment_item in equipped_items:
            bonuses = equipment_item.item_definition.stat_bonuses or {}
            max_hp += int(bonuses.get("max_hp", 0))
            attack += int(bonuses.get("attack", 0))
            defense += int(bonuses.get("defense", 0))
            crit_chance += float(bonuses.get("crit_chance", 0.0))
            crit_damage += float(bonuses.get("crit_damage", 0.0))
            dodge += float(bonuses.get("dodge", 0.0))

        crit_chance = min(crit_chance, 0.75)
        dodge = min(dodge, 0.50)
        crit_damage = max(crit_damage, 1.0)

        return Stats(
            max_hp=max_hp,
            attack=attack,
            defense=defense,
            crit_chance=crit_chance,
            crit_damage=crit_damage,
            dodge=dodge,
        )