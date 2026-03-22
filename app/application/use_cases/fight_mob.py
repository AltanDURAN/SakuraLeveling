from app.domain.services.combat_service import CombatService
from app.domain.services.loot_service import LootService
from app.domain.services.progression_service import ProgressionService
from app.domain.services.stats_service import StatsService
from app.domain.value_objects.battle_result import BattleResult
from app.infrastructure.db.repositories.equipment_repository import EquipmentRepository
from app.infrastructure.db.repositories.inventory_repository import InventoryRepository
from app.infrastructure.db.repositories.item_repository import ItemRepository
from app.infrastructure.db.repositories.mob_repository import MobRepository
from app.infrastructure.db.repositories.player_repository import PlayerRepository


class FightMobUseCase:
    def __init__(
        self,
        player_repository: PlayerRepository,
        equipment_repository: EquipmentRepository,
        mob_repository: MobRepository,
        inventory_repository: InventoryRepository,
        item_repository: ItemRepository,
        stats_service: StatsService,
        combat_service: CombatService,
        loot_service: LootService,
        progression_service: ProgressionService,
    ):
        self.player_repository = player_repository
        self.equipment_repository = equipment_repository
        self.mob_repository = mob_repository
        self.inventory_repository = inventory_repository
        self.item_repository = item_repository
        self.stats_service = stats_service
        self.combat_service = combat_service
        self.loot_service = loot_service
        self.progression_service = progression_service

    def execute(
        self,
        discord_id: int,
        username: str,
        display_name: str,
        mob_code: str,
    ) -> BattleResult | None:
        profile = self.player_repository.get_or_create_by_discord_id(
            discord_id=discord_id,
            username=username,
            display_name=display_name,
        )

        mob = self.mob_repository.get_by_code(mob_code)
        if mob is None:
            return None

        equipped_items = self.equipment_repository.list_by_player_id(profile.player.id)
        player_stats = self.stats_service.calculate_player_stats(profile, equipped_items)

        result = self.combat_service.fight_player_vs_mob(
            player_stats=player_stats,
            mob=mob,
        )

        if not result.victory:
            return result

        self.player_repository.add_gold(profile.player.id, result.gold_gained)

        new_level, new_xp, new_skill_points = self.progression_service.apply_level_up(
            current_level=profile.progression.level,
            current_xp=profile.progression.xp,
            gained_xp=result.xp_gained,
            current_skill_points=profile.progression.skill_points,
        )

        leveled_up = new_level > profile.progression.level

        self.player_repository.apply_progression(
            player_id=profile.player.id,
            new_level=new_level,
            new_xp=new_xp,
            new_skill_points=new_skill_points,
        )

        dropped_items = self.loot_service.generate_loot(mob)

        for item_code, quantity in dropped_items:
            item = self.item_repository.get_by_code(item_code)
            if item is None:
                continue

            self.inventory_repository.add_item(
                player_id=profile.player.id,
                item_definition_id=item.id,
                quantity=quantity,
            )

        result.items_gained = dropped_items
        result.leveled_up = leveled_up
        result.new_level = new_level if leveled_up else None

        return result