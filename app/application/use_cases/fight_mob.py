from app.domain.services.combat_service import CombatService
from app.domain.services.stats_service import StatsService
from app.domain.value_objects.battle_result import BattleResult
from app.infrastructure.db.repositories.equipment_repository import EquipmentRepository
from app.infrastructure.db.repositories.mob_repository import MobRepository
from app.infrastructure.db.repositories.player_repository import PlayerRepository


class FightMobUseCase:
    def __init__(
        self,
        player_repository: PlayerRepository,
        equipment_repository: EquipmentRepository,
        mob_repository: MobRepository,
        stats_service: StatsService,
        combat_service: CombatService,
    ):
        self.player_repository = player_repository
        self.equipment_repository = equipment_repository
        self.mob_repository = mob_repository
        self.stats_service = stats_service
        self.combat_service = combat_service

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

        if result.victory:
            self.player_repository.add_xp(profile.player.id, result.xp_gained)
            self.player_repository.add_gold(profile.player.id, result.gold_gained)

        return result