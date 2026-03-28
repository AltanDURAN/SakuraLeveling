from app.infrastructure.db.repositories.class_repository import ClassRepository
from app.infrastructure.db.repositories.player_repository import PlayerRepository


class ChangePlayerClassUseCase:
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
        class_code: str,
    ) -> bool:
        profile = self.player_repository.get_or_create_by_discord_id(
            discord_id=discord_id,
            username=username,
            display_name=display_name,
        )

        class_definition = self.class_repository.get_by_code(class_code)
        if class_definition is None:
            return False

        self.class_repository.set_player_class(
            player_id=profile.player.id,
            class_id=class_definition.id,
        )
        return True