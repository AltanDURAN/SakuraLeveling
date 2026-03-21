from app.infrastructure.db.repositories.equipment_repository import EquipmentRepository
from app.infrastructure.db.repositories.inventory_repository import InventoryRepository
from app.infrastructure.db.repositories.player_repository import PlayerRepository


class EquipItemUseCase:
    def __init__(
        self,
        player_repository: PlayerRepository,
        inventory_repository: InventoryRepository,
        equipment_repository: EquipmentRepository,
    ):
        self.player_repository = player_repository
        self.inventory_repository = inventory_repository
        self.equipment_repository = equipment_repository

    def execute(
        self,
        discord_id: int,
        username: str,
        display_name: str,
        item_code: str,
        slot: str,
    ) -> bool:
        profile = self.player_repository.get_or_create_by_discord_id(
            discord_id=discord_id,
            username=username,
            display_name=display_name,
        )

        inventory_items = self.inventory_repository.list_by_player_id(profile.player.id)

        matched_item = next(
            (item for item in inventory_items if item.item_definition.code == item_code),
            None,
        )

        if matched_item is None:
            return False

        self.equipment_repository.equip_item(
            player_id=profile.player.id,
            item_definition_id=matched_item.item_definition.id,
            slot=slot,
        )
        return True