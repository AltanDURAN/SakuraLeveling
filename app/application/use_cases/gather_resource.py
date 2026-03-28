import random

from app.domain.services.profession_service import ProfessionService


class GatherResourceUseCase:
    def __init__(
        self,
        player_repository,
        profession_repository,
        inventory_repository,
        item_repository,
        profession_service: ProfessionService,
    ):
        self.player_repository = player_repository
        self.profession_repository = profession_repository
        self.inventory_repository = inventory_repository
        self.item_repository = item_repository
        self.profession_service = profession_service

    def execute(self, discord_id, username, display_name, profession_code):
        profile = self.player_repository.get_or_create_by_discord_id(
            discord_id, username, display_name
        )

        profession = self.profession_repository.get_definition_by_code(profession_code)
        if not profession:
            return False, "Métier introuvable"

        player_prof = self.profession_repository.get_or_create_player_profession(
            profile.player.id,
            profession.id,
        )

        # logique simple V1
        gained_xp = random.randint(5, 15)
        item_code = "wood" if profession_code == "woodcutting" else "stone"
        quantity = random.randint(1, 3)

        item = self.item_repository.get_by_code(item_code)
        if item:
            self.inventory_repository.add_item(
                player_id=profile.player.id,
                item_definition_id=item.id,
                quantity=quantity,
            )

        new_level, new_xp = self.profession_service.apply_xp(
            player_prof.level,
            player_prof.xp,
            gained_xp,
        )

        self.profession_repository.update_progress(
            profile.player.id,
            profession.id,
            new_level,
            new_xp,
        )

        return True, f"+{quantity} {item_code} | +{gained_xp} XP métier"