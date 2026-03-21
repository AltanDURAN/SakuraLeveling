from app.domain.entities.player_equipment_item import PlayerEquipmentItem
from app.infrastructure.db.repositories.equipment_repository import EquipmentRepository
from app.infrastructure.db.repositories.player_repository import PlayerRepository


class GetPlayerEquipmentUseCase:
    def __init__(
        self,
        player_repository: PlayerRepository,
        equipment_repository: EquipmentRepository,
    ):
        self.player_repository = player_repository
        self.equipment_repository = equipment_repository

    def execute(
        self,
        discord_id: int,
        username: str,
        display_name: str,
    ) -> list[PlayerEquipmentItem]:
        profile = self.player_repository.get_or_create_by_discord_id(
            discord_id=discord_id,
            username=username,
            display_name=display_name,
        )

        return self.equipment_repository.list_by_player_id(profile.player.id)