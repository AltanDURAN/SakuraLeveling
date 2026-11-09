"""Reset de saison : tout le monde repart de zéro.

Décision de la saison 1 : on recommence À NEUF. Seule l'identité Discord des
joueurs est conservée (table `players`) ; tout le reste — progression, or,
équipement, titres, scores des défis, maîtrise des artisans, affinités et
essences — est effacé.

Effacé aussi, parce que ça n'a plus de sens d'une saison à l'autre : le world
boss en cours et son historique, les événements, les annonces de brocante,
les échanges, l'historique des défis, l'offrande et TOUTE la surveillance du
site admin (journal, photos des joueurs, alertes) — elle repart du repère
`season` posé à la fin du reset. Ses RÉGLAGES (`monitoring.json`) restent.
Le contenu du jeu (objets, monstres, recettes, boutique) n'est PAS touché :
il vit dans les JSON et se ré-applique au seed.

Le PARCOURS D'ARRIVÉE repart aussi du début (décision de l'auteur,
09/11/2026) : règlements acceptés et aventuriers effacés (les tutoriels
partent avec les joueurs), tout le monde repasse par le règlement. Les rôles
Discord (rangs, Aventurier) sont retirés par le BOT (file `admin_commands`,
action `reset_journey_roles`, ou directement par `/admin lancer_saison`) :
la base ne peut pas toucher à Discord elle-même.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.application.use_cases.reset_player import ResetPlayerUseCase
from app.domain.services.monitoring import kinds
from app.infrastructure.db.models.adventurer_model import AdventurerModel
from app.infrastructure.db.models.event_model import (
    ActiveEventModel,
    EventParticipationModel,
    EventSchedulerStateModel,
)
from app.infrastructure.db.models.gear_model import PlayerGearModel
from app.infrastructure.db.models.marketplace_listing_model import MarketplaceListingModel
from app.infrastructure.db.models.monitoring_model import (
    GameEventModel,
    MonitoringAlertModel,
    PlayerDailySnapshotModel,
)
from app.infrastructure.db.models.offering_model import OfferingContributionModel, OfferingStateModel
from app.infrastructure.db.models.player_model import PlayerModel
from app.infrastructure.db.models.progression_model import PlayerProgressionModel
from app.infrastructure.db.models.resource_model import PlayerResourceModel
from app.infrastructure.db.models.records_model import RecordBoardModel, RecordHolderModel
from app.infrastructure.db.models.role_trial_model import RoleTrialScoreModel, RoleTrialWeekModel
from app.infrastructure.db.models.rules_model import RulesAcceptanceModel
from app.infrastructure.db.models.trade_model import TradeItemModel, TradeModel
from app.infrastructure.db.models.world_boss_model import (
    WorldBossModel,
    WorldBossParticipationModel,
)
from app.infrastructure.db.repositories.admin_command_repository import (
    AdminCommandRepository,
)
from app.infrastructure.db.unit_of_work import atomic
from app.infrastructure.monitoring import telemetry

#: Action du bot qui retire les rôles du parcours à tous (`AdminBridgeCog`).
JOURNEY_ROLES_ACTION = "reset_journey_roles"

#: Tables globales vidées entièrement (dans cet ordre : enfants d'abord).
GLOBAL_TABLES = (
    WorldBossParticipationModel,
    WorldBossModel,
    EventParticipationModel,
    ActiveEventModel,
    EventSchedulerStateModel,
    MarketplaceListingModel,
    TradeItemModel,
    TradeModel,
    RoleTrialScoreModel,
    RoleTrialWeekModel,
    RecordHolderModel,
    OfferingContributionModel,
    OfferingStateModel,
    # Parcours d'arrivée (par compte Discord) : tout le monde repasse par le
    # règlement et le tutoriel.
    RulesAcceptanceModel,
    AdventurerModel,
    # Surveillance : les lignes sans joueur (fuites, arrivées, alertes du
    # serveur, rapports envoyés) — celles d'un joueur partent avec lui.
    GameEventModel,
    PlayerDailySnapshotModel,
    MonitoringAlertModel,
)


@dataclass
class SeasonResetReport:
    players: int = 0
    cleared: dict[str, int] = field(default_factory=dict)
    roles_queued: bool = False
    #: Ce qui part avec les joueurs (pour l'aperçu).
    gold_total: int = 0
    max_level: int = 1
    gear_total: int = 0
    season: int = 0


def _count(session: Session, model) -> int:
    return session.execute(select(func.count()).select_from(model)).scalar_one()


def preview_season_reset(session: Session) -> SeasonResetReport:
    """Ce que le reset effacerait — sans rien modifier."""
    report = SeasonResetReport(
        players=_count(session, PlayerModel),
        gold_total=int(session.execute(select(func.coalesce(func.sum(PlayerResourceModel.gold), 0))).scalar_one()),
        max_level=int(session.execute(select(func.coalesce(func.max(PlayerProgressionModel.level), 1))).scalar_one()),
        gear_total=_count(session, PlayerGearModel),
    )
    for model in GLOBAL_TABLES:
        report.cleared[model.__tablename__] = _count(session, model)
    return report


def reset_season(session: Session, queue_role_reset: bool = True, season: int = 1) -> SeasonResetReport:
    """Remet tous les joueurs à zéro, vide les tables de saison et pose le
    repère « début de la saison N » dans le journal de surveillance.

    Tout ou rien : un plantage au 30e joueur n'en laisse pas 29 remis à zéro.
    L'appelant fait la sauvegarde AVANT : rien ici n'est réversible.
    """
    report = preview_season_reset(session)
    report.season = season
    with atomic(session):
        player_ids = session.execute(select(PlayerModel.id)).scalars().all()
        reset_player = ResetPlayerUseCase()
        for player_id in player_ids:
            reset_player.execute(session, player_id)
        for model in GLOBAL_TABLES:
            session.execute(delete(model))
        # Le tableau des records se réécrit dans les 5 minutes (sans attendre minuit).
        session.execute(update(RecordBoardModel).values(last_day=None))
        telemetry.record(session, kinds.SEASON_START, ref=f"saison {season}", qty=season)
        if queue_role_reset:
            AdminCommandRepository(session).enqueue(JOURNEY_ROLES_ACTION)
            report.roles_queued = True
    return report
