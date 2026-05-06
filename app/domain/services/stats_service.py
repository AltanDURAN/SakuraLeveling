from app.domain.entities.class_definition import ClassDefinition
from app.domain.entities.player_equipment_item import PlayerEquipmentItem
from app.domain.entities.player_profile import PlayerProfile
from app.domain.services.title_bonus_service import TitleBonuses
from app.domain.value_objects.skill_bonuses import SkillBonuses
from app.domain.value_objects.stats import Stats


class StatsService:
    def calculate_player_stats(
        self,
        profile: PlayerProfile,
        equipped_items: list[PlayerEquipmentItem],
        active_class: ClassDefinition | None = None,
        skill_bonuses: SkillBonuses | None = None,
        title_bonuses: TitleBonuses | None = None,
    ) -> Stats:
        level = profile.progression.level

        max_hp = 100 + (level - 1) * 10
        attack = 10 + (level - 1) * 2
        defense = 5 + (level - 1) * 1

        crit_chance = 5
        crit_damage = 150
        dodge = 0

        base_hp_regeneration = 5
        hp_regeneration = base_hp_regeneration

        base_speed = 5
        speed = base_speed

        if active_class is not None:
            bonuses = active_class.stat_bonuses or {}
            max_hp += int(bonuses.get("max_hp", 0))
            attack += int(bonuses.get("attack", 0))
            defense += int(bonuses.get("defense", 0))
            speed += int(bonuses.get("speed", 0))
            crit_chance += float(bonuses.get("crit_chance", 0))
            crit_damage += float(bonuses.get("crit_damage", 0))
            dodge += float(bonuses.get("dodge", 0))
            hp_regeneration += int(bonuses.get("hp_regeneration", 0))

        for equipment_item in equipped_items:
            bonuses = equipment_item.item_definition.stat_bonuses or {}
            max_hp += int(bonuses.get("max_hp", 0))
            attack += int(bonuses.get("attack", 0))
            defense += int(bonuses.get("defense", 0))
            speed += int(bonuses.get("speed", 0))
            crit_chance += float(bonuses.get("crit_chance", 0))
            crit_damage += float(bonuses.get("crit_damage", 0))
            dodge += float(bonuses.get("dodge", 0))
            hp_regeneration += int(bonuses.get("hp_regeneration", 0))

        # 4e étage : bonus de l'arbre de compétences (flat additif puis %).
        # Appliqué après équipement/classe et AVANT les caps finaux pour que
        # crit_chance / dodge restent bornés.
        if skill_bonuses is not None:
            crit_chance += skill_bonuses.crit_chance_flat
            crit_damage += skill_bonuses.crit_damage_flat
            dodge += skill_bonuses.dodge_flat
            speed += skill_bonuses.speed_flat
            hp_regeneration += skill_bonuses.hp_regeneration_flat

            max_hp = round(max_hp * (1 + skill_bonuses.hp_max_percent))
            attack = round(attack * (1 + skill_bonuses.atk_percent))
            defense = round(defense * (1 + skill_bonuses.def_percent))

        crit_chance = min(crit_chance, 75)
        dodge = min(dodge, 50)
        crit_damage = max(crit_damage, 100)
        hp_regeneration = max(0, hp_regeneration)
        speed = max(1, speed)

        stats = Stats(
            max_hp=max_hp,
            attack=attack,
            defense=defense,
            speed=speed,
            crit_chance=crit_chance,
            crit_damage=crit_damage,
            dodge=dodge,
            hp_regeneration=hp_regeneration,
        )

        # 5e étage : bonus de titres exclusifs (Champion 1v1 etc.).
        # Appliqués APRÈS les caps standards : un Champion 1v1 peut donc
        # dépasser le cap crit/dodge de 1 pt, c'est l'avantage du titre.
        if title_bonuses is not None:
            stats = title_bonuses.apply_to_stats(stats)

        return stats