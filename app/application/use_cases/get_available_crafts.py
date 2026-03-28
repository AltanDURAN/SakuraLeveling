from app.domain.entities.craft_recipe import CraftRecipe
from app.infrastructure.db.repositories.craft_repository import CraftRepository


class GetAvailableCraftsUseCase:
    def __init__(self, craft_repository: CraftRepository):
        self.craft_repository = craft_repository

    def execute(self) -> list[CraftRecipe]:
        return self.craft_repository.list_all()