from app.domain.value_objects.stats import Stats
from app.domain.services.stats_service import StatsService
from app.infrastructure.db.repositories.class_repository import ClassRepository
from app.infrastructure.db.repositories.equipment_repository import EquipmentRepository
from app.infrastructure.db.repositories.player_repository import PlayerRepository


class GetPlayerStatsUseCase:
    def __init__(
        self,
        player_repository: PlayerRepository,
        equipment_repository: EquipmentRepository,
        class_repository: ClassRepository,
        stats_service: StatsService,
    ):
        self.player_repository = player_repository
        self.equipment_repository = equipment_repository
        self.class_repository = class_repository
        self.stats_service = stats_service

    def execute(
        self,
        discord_id: int,
        username: str,
        display_name: str,
    ) -> Stats:
        profile = self.player_repository.get_or_create_by_discord_id(
            discord_id=discord_id,
            username=username,
            display_name=display_name,
        )

        equipped_items = self.equipment_repository.list_by_player_id(profile.player.id)
        active_class = self.class_repository.get_current_class_for_player(profile.player.id)

        return self.stats_service.calculate_player_stats(
            profile=profile,
            equipped_items=equipped_items,
            active_class=active_class,
        )