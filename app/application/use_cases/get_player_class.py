from app.domain.entities.class_definition import ClassDefinition
from app.infrastructure.db.repositories.class_repository import ClassRepository
from app.infrastructure.db.repositories.player_repository import PlayerRepository


class GetPlayerClassUseCase:
    def __init__(
        self,
        player_repository: PlayerRepository,
        class_repository: ClassRepository,
    ):
        self.player_repository = player_repository
        self.class_repository = class_repository

    def execute(
        self,
        discord_id: int,
        username: str,
        display_name: str,
    ) -> ClassDefinition | None:
        profile = self.player_repository.get_or_create_by_discord_id(
            discord_id=discord_id,
            username=username,
            display_name=display_name,
        )

        self.class_repository.get_or_create_player_class_state(profile.player.id)
        return self.class_repository.get_current_class_for_player(profile.player.id)