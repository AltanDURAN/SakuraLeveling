"""Quêtes quotidiennes ADAPTÉES à chaque joueur (cf. `quest_engine`).

    1. Au premier passage de la période (commande ou action en jeu), le joueur
       reçoit 3 quêtes tirées pour LUI : cible de sa zone, quantité à son
       niveau, objectif de son rôle (une par difficulté si possible).
    2. Les évènements de jeu les font avancer via `DailyQuestProgressService`.
    3. `ClaimAllDailyUseCase` réclame d'un coup toutes les quêtes terminées.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.application.use_cases.quest_engine import (
    ClaimAllResult,
    QuestProgressService,
    QuestStatus,
    claim_all,
    ensure_assigned,
    statuses,
)
from app.domain.services.progression_service import ProgressionService
from app.infrastructure.daily_quests.quest_loader import get_definition, list_definitions
from app.infrastructure.db.repositories.inventory_repository import InventoryRepository
from app.infrastructure.db.repositories.item_repository import ItemRepository
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.repositories.daily_quest_repository import DailyQuestRepository


def get_current_day_start(now: datetime | None = None) -> datetime:
    """Aujourd'hui 00:00 heure de Paris (CEST/CET selon DST), en UTC pour le
    stockage SQLite. Reset à minuit Paris, comme le /daily."""
    from zoneinfo import ZoneInfo
    paris = ZoneInfo("Europe/Paris")
    now = now or datetime.now(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    midnight = now.astimezone(paris).replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight.astimezone(UTC)


@dataclass
class DailyQuestState:
    day_start: datetime
    quests: list[QuestStatus] = field(default_factory=list)

    @property
    def claimable_count(self) -> int:
        return sum(1 for q in self.quests if q.completed and not q.claimed)


class GetDailyQuestsUseCase:
    def __init__(self, player_repository: PlayerRepository,
                 quest_repository: DailyQuestRepository) -> None:
        self.player_repository = player_repository
        self.quest_repository = quest_repository

    def execute(self, discord_id: int, username: str, display_name: str,
                rank: str | None = None) -> DailyQuestState:
        """`rank` : rang Discord du joueur (sa zone la plus haute) s'il est connu."""
        profile = self.player_repository.get_or_create_by_discord_id(
            discord_id=discord_id, username=username, display_name=display_name)
        level = profile.progression.level
        start = get_current_day_start()
        ensure_assigned(self.quest_repository.session, self.quest_repository, list_definitions(),
                        profile.player.id, start, level, rank=rank)
        assignments = self.quest_repository.list_for_player(profile.player.id, start)
        return DailyQuestState(start, statuses(assignments, get_definition, level))


class ClaimAllDailyUseCase:
    """Réclame d'un coup toutes les quêtes complétées non encore réclamées."""

    def __init__(self, player_repository: PlayerRepository, quest_repository: DailyQuestRepository,
                 item_repository: ItemRepository, inventory_repository: InventoryRepository,
                 progression_service: ProgressionService | None = None) -> None:
        self.player_repository = player_repository
        self.quest_repository = quest_repository
        self.item_repository = item_repository
        self.inventory_repository = inventory_repository
        self.progression_service = progression_service or ProgressionService()

    def execute(self, discord_id: int, username: str, display_name: str) -> ClaimAllResult:
        profile = self.player_repository.get_or_create_by_discord_id(
            discord_id=discord_id, username=username, display_name=display_name)
        return claim_all(profile, self.quest_repository, get_definition, get_current_day_start(),
                         self.player_repository, self.item_repository,
                         self.inventory_repository, self.progression_service)


class DailyQuestProgressService(QuestProgressService):
    def period_start(self) -> datetime:
        return get_current_day_start()

    def templates(self):
        return list_definitions()
