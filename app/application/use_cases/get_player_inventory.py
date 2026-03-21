from app.domain.entities.player_inventory_item import PlayerInventoryItem
from app.infrastructure.db.repositories.inventory_repository import InventoryRepository
from app.infrastructure.db.repositories.player_repository import PlayerRepository


class GetPlayerInventoryUseCase:
    def __init__(
        self,
        player_repository: PlayerRepository,
        inventory_repository: InventoryRepository,
    ):
        self.player_repository = player_repository
        self.inventory_repository = inventory_repository

    def execute(
        self,
        discord_id: int,
        username: str,
        display_name: str,
    ) -> tuple[int, list[PlayerInventoryItem]]:
        profile = self.player_repository.get_or_create_by_discord_id(
            discord_id=discord_id,
            username=username,
            display_name=display_name,
        )

        items = self.inventory_repository.list_by_player_id(profile.player.id)
        return profile.player.id, items