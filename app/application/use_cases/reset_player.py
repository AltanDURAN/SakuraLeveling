from datetime import datetime, UTC

from sqlalchemy import delete, or_, select, update
from sqlalchemy.orm import Session

from app.infrastructure.db.models.cooldown_model import PlayerCooldownModel
from app.infrastructure.db.models.equipment_model import PlayerEquipmentItemModel
from app.infrastructure.db.models.equipment_set_model import (
    PlayerEquipmentSetItemModel,
    PlayerEquipmentSetModel,
)
from app.infrastructure.db.models.inventory_model import PlayerInventoryItemModel
from app.infrastructure.db.models.player_career_stats_model import PlayerCareerStatsModel
from app.infrastructure.db.models.player_class_state_model import PlayerClassStateModel
from app.infrastructure.db.models.player_duel_rank_model import PlayerDuelRankModel
from app.infrastructure.db.models.player_health_state_model import PlayerHealthStateModel
from app.infrastructure.db.models.player_mob_kill_model import PlayerMobKillModel
from app.infrastructure.db.models.player_skill_allocation_model import (
    PlayerSkillAllocationModel,
)
from app.infrastructure.db.models.help_subscriber_model import HelpSubscriberModel
from app.infrastructure.db.models.marketplace_listing_model import MarketplaceListingModel
from app.infrastructure.db.models.player_title_model import PlayerTitleModel
from app.infrastructure.db.models.daily_quest_model import DailyQuestAssignmentModel
from app.infrastructure.db.models.weekly_quest_model import WeeklyQuestAssignmentModel
from app.infrastructure.db.models.world_boss_model import WorldBossParticipationModel
from app.infrastructure.db.models.profession_model import PlayerProfessionModel
from app.infrastructure.db.models.progression_model import PlayerProgressionModel
from app.infrastructure.db.models.quest_model import PlayerQuestStateModel
from app.infrastructure.db.models.resource_model import PlayerResourceModel
from app.infrastructure.db.models.trade_model import TradeItemModel, TradeModel


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

        # Sets d'équipement : DELETE en cascade via FK on the model side.
        # On commence par récupérer les ids puis on supprime les set_items
        # liés. ondelete=CASCADE le ferait au niveau DB mais SQLite peut
        # ne pas l'honorer selon les pragmas — on est explicite.
        set_ids_subquery = select(PlayerEquipmentSetModel.id).where(
            PlayerEquipmentSetModel.player_id == player_id,
        )
        session.execute(
            delete(PlayerEquipmentSetItemModel).where(
                PlayerEquipmentSetItemModel.equipment_set_id.in_(set_ids_subquery),
            )
        )

        # Tables 1:N — DELETE par player_id
        for model_cls in (
            PlayerInventoryItemModel,
            PlayerEquipmentItemModel,
            PlayerEquipmentSetModel,
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
            DailyQuestAssignmentModel,
            HelpSubscriberModel,
        ):
            session.execute(delete(model_cls).where(model_cls.player_id == player_id))

        # Marketplace : on purge les annonces actives du joueur (clé
        # `seller_player_id`). Les items "en consigne" sont perdus côté
        # brocante (l'inventaire étant déjà vidé), ce qui est cohérent
        # avec l'esprit "reset complet".
        session.execute(
            delete(MarketplaceListingModel).where(
                MarketplaceListingModel.seller_player_id == player_id
            )
        )

        # On efface aussi `last_buyer_player_id` sur les annonces déjà
        # vendues, pour ne pas laisser de référence vers un profil reseté.
        session.execute(
            update(MarketplaceListingModel)
            .where(MarketplaceListingModel.last_buyer_player_id == player_id)
            .values(last_buyer_player_id=None)
        )

        # Trades : on purge tous les trades où le joueur est initiator ou
        # target (en cours, accepté, refusé, etc.) ainsi que leurs items.
        # Pendant qu'on y est, idempotent sur les trades sans item.
        trade_ids_subquery = select(TradeModel.id).where(
            or_(
                TradeModel.initiator_player_id == player_id,
                TradeModel.target_player_id == player_id,
            )
        )
        session.execute(
            delete(TradeItemModel).where(TradeItemModel.trade_id.in_(trade_ids_subquery))
        )
        session.execute(
            delete(TradeModel).where(
                or_(
                    TradeModel.initiator_player_id == player_id,
                    TradeModel.target_player_id == player_id,
                )
            )
        )

        session.commit()
