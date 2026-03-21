from app.domain.entities.player_profile import PlayerProfile
from app.infrastructure.db.repositories.player_repository import PlayerRepository


class GetPlayerProfileUseCase:
    def __init__(self, player_repository: PlayerRepository):
        self.player_repository = player_repository

    def execute(
        self,
        discord_id: int,
        username: str,
        display_name: str,
    ) -> PlayerProfile:
        return self.player_repository.get_or_create_by_discord_id(
            discord_id=discord_id,
            username=username,
            display_name=display_name,
        )