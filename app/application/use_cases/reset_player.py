from datetime import datetime, UTC

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.infrastructure.db.models.cooldown_model import PlayerCooldownModel
from app.infrastructure.db.models.equipment_model import PlayerEquipmentItemModel
from app.infrastructure.db.models.inventory_model import PlayerInventoryItemModel
from app.infrastructure.db.models.player_career_stats_model import PlayerCareerStatsModel
from app.infrastructure.db.models.player_class_state_model import PlayerClassStateModel
from app.infrastructure.db.models.player_duel_rank_model import PlayerDuelRankModel
from app.infrastructure.db.models.player_health_state_model import PlayerHealthStateModel
from app.infrastructure.db.models.player_mob_kill_model import PlayerMobKillModel
from app.infrastructure.db.models.player_skill_allocation_model import (
    PlayerSkillAllocationModel,
)
from app.infrastructure.db.models.marketplace_listing_model import MarketplaceListingModel
from app.infrastructure.db.models.player_title_model import PlayerTitleModel
from app.infrastructure.db.models.weekly_quest_model import WeeklyQuestAssignmentModel
from app.infrastructure.db.models.world_boss_model import WorldBossParticipationModel
from app.infrastructure.db.models.profession_model import PlayerProfessionModel
from app.infrastructure.db.models.progression_model import PlayerProgressionModel
from app.infrastructure.db.models.quest_model import PlayerQuestStateModel
from app.infrastructure.db.models.resource_model import PlayerResourceModel


class ResetPlayerUseCase:
    """Remet le profil d'un joueur à zéro tout en gardant son identité Discord.

    Conserve : `players` (id, discord_id, username, display_name, timestamps).
    Réinitialise : niveau/XP/skill_points, or, classes, équipement, inventaire,
    quêtes, cooldowns, professions, kills, état HP.
    """

    def execute(self, session: Session, player_id: int) -> None:
        now = datetime.now(UTC)

        # Tables 1:1 avec le joueur — UPDATE
        progression = session.get(PlayerProgressionModel, player_id)
        if progression is not None:
            progression.level = 1
            progression.xp = 0
            progression.skill_points = 0
            progression.updated_at = now

        resources = session.get(PlayerResourceModel, player_id)
        if resources is not None:
            resources.gold = 0
            resources.daily_streak = 0
            resources.updated_at = now

        # Tables 1:N — DELETE par player_id
        for model_cls in (
            PlayerInventoryItemModel,
            PlayerEquipmentItemModel,
            PlayerClassStateModel,
            PlayerQuestStateModel,
            PlayerCooldownModel,
            PlayerHealthStateModel,
            PlayerMobKillModel,
            PlayerProfessionModel,
            PlayerCareerStatsModel,
            PlayerSkillAllocationModel,
            PlayerDuelRankModel,
            WorldBossParticipationModel,
            PlayerTitleModel,
            WeeklyQuestAssignmentModel,
        ):
            session.execute(delete(model_cls).where(model_cls.player_id == player_id))

        # Marketplace : la clé est `seller_player_id` (pas player_id).
        # On purge les annonces actives du joueur — les items "en consigne"
        # sont perdus côté brocante (l'inventaire étant déjà vidé), ce qui
        # est cohérent avec l'esprit "reset complet".
        session.execute(
            delete(MarketplaceListingModel).where(
                MarketplaceListingModel.seller_player_id == player_id
            )
        )

        session.commit()
