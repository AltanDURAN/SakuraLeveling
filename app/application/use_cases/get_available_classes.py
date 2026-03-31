from app.domain.services.class_service import ClassService
from app.infrastructure.db.repositories.class_repository import ClassRepository
from app.infrastructure.db.repositories.inventory_repository import InventoryRepository
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.repositories.profession_repository import ProfessionRepository


class GetAvailableClassesUseCase:
    def __init__(
        self,
        player_repository: PlayerRepository,
        class_repository: ClassRepository,
        profession_repository: ProfessionRepository,
        inventory_repository: InventoryRepository,
        class_service: ClassService,
    ):
        self.player_repository = player_repository
        self.class_repository = class_repository
        self.profession_repository = profession_repository
        self.inventory_repository = inventory_repository
        self.class_service = class_service

    def execute(
        self,
        discord_id: int,
        username: str,
        display_name: str,
    ) -> list[dict]:
        profile = self.player_repository.get_or_create_by_discord_id(
            discord_id=discord_id,
            username=username,
            display_name=display_name,
        )

        classes = self.class_repository.list_all()
        player_professions = self.profession_repository.list_player_professions_with_definitions(
            profile.player.id
        )
        inventory_items = self.inventory_repository.list_by_player_id(profile.player.id)

        results = []

        for class_definition in classes:
            unlocked = self.class_service.can_unlock_class(
                class_definition=class_definition,
                player_professions=player_professions,
                inventory_items=inventory_items,
            )

            results.append(
                {
                    "class_definition": class_definition,
                    "unlocked": unlocked,
                }
            )

        return results