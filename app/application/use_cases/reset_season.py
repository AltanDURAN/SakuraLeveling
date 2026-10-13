"""Reset de saison : tout le monde repart de zéro.

Décision de la saison 1 : on recommence À NEUF. Seule l'identité Discord des
joueurs est conservée (table `players`) ; tout le reste — progression, or,
équipement, titres, classement des duels, maîtrise des artisans, affinités et
essences — est effacé.

Effacé aussi, parce que ça n'a plus de sens d'une saison à l'autre : le world
boss en cours et son historique, les événements, les annonces de brocante et
les échanges. Le contenu du jeu (objets, monstres, recettes, boutique) n'est
PAS touché : il vit dans les JSON et se ré-applique au seed.

Les rôles de rang Discord sont remis au Rang F par le BOT (file
`admin_commands`, action `reset_rank_roles`) : la base ne peut pas toucher à
Discord elle-même.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.application.use_cases.reset_player import ResetPlayerUseCase
from app.infrastructure.db.models.event_model import (
    ActiveEventModel,
    EventParticipationModel,
    EventSchedulerStateModel,
)
from app.infrastructure.db.models.marketplace_listing_model import MarketplaceListingModel
from app.infrastructure.db.models.player_model import PlayerModel
from app.infrastructure.db.models.trade_model import TradeItemModel, TradeModel
from app.infrastructure.db.models.work_order_model import PlayerWorkOrderModel
from app.infrastructure.db.models.world_boss_model import (
    WorldBossModel,
    WorldBossParticipationModel,
)
from app.infrastructure.db.repositories.admin_command_repository import (
    AdminCommandRepository,
)

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
    PlayerWorkOrderModel,
)


@dataclass
class SeasonResetReport:
    players: int = 0
    cleared: dict[str, int] = field(default_factory=dict)
    roles_queued: bool = False


def preview_season_reset(session: Session) -> SeasonResetReport:
    """Ce que le reset effacerait — sans rien modifier."""
    report = SeasonResetReport(
        players=session.execute(select(func.count()).select_from(PlayerModel)).scalar_one(),
    )
    for model in GLOBAL_TABLES:
        report.cleared[model.__tablename__] = session.execute(
            select(func.count()).select_from(model)
        ).scalar_one()
    return report


def reset_season(session: Session, queue_role_reset: bool = True) -> SeasonResetReport:
    """Remet tous les joueurs à zéro et vide les tables de saison.

    L'appelant fait la sauvegarde AVANT : rien ici n'est réversible.
    """
    report = preview_season_reset(session)
    player_ids = session.execute(select(PlayerModel.id)).scalars().all()
    reset_player = ResetPlayerUseCase()
    for player_id in player_ids:
        reset_player.execute(session, player_id)
    for model in GLOBAL_TABLES:
        session.execute(delete(model))
    if queue_role_reset:
        AdminCommandRepository(session).enqueue("reset_rank_roles")
        report.roles_queued = True
    session.commit()
    return report
