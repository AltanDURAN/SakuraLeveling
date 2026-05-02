"""Use cases du système de quêtes hebdomadaires.

Workflow :
    1. Au premier appel `/weekly` de la semaine, chaque joueur reçoit 3 quêtes
       tirées au hasard (mix easy/medium/hard si possible).
    2. Les évènements de jeu (kill, duel win, craft, gather, gold earned,
       boss damage, daily streak) appellent `WeeklyQuestProgressService` qui
       incrémente toutes les quêtes pertinentes du joueur pour la semaine
       courante.
    3. Quand une quête atteint son objectif → completed=True, claimed=False.
    4. `/weekly_claim` retire les récompenses (gold + xp + items + level-up).

Convention semaine :
    week_start = lundi 00:00 UTC de la semaine courante. Tous les joueurs
    partagent la même clé de rotation.
"""

from dataclasses import dataclass, field
from datetime import datetime, UTC, timedelta

from app.domain.entities.weekly_quest_definition import WeeklyQuestDefinition
from app.domain.services.progression_service import ProgressionService
from app.infrastructure.db.repositories.inventory_repository import InventoryRepository
from app.infrastructure.db.repositories.item_repository import ItemRepository
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.repositories.weekly_quest_repository import (
    WeeklyQuestRepository,
)
from app.infrastructure.weekly_quests.quest_loader import (
    get_definition,
    list_for_objective_type,
    pick_random_assignment,
)


def get_current_week_start(now: datetime | None = None) -> datetime:
    """Retourne le lundi 00:00 UTC de la semaine de `now`."""
    now = now or datetime.now(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    # weekday() : lundi=0 ... dimanche=6
    days_since_monday = now.weekday()
    monday = now - timedelta(days=days_since_monday)
    return monday.replace(hour=0, minute=0, second=0, microsecond=0)


@dataclass
class QuestStatus:
    code: str
    name: str
    description: str
    tier: str
    progress: int
    objective_quantity: int
    completed: bool
    claimed: bool
    reward_gold: int
    reward_xp: int
    reward_items: list


@dataclass
class WeeklyQuestState:
    week_start: datetime
    quests: list[QuestStatus] = field(default_factory=list)


class GetWeeklyQuestsUseCase:
    """Charge l'état des quêtes du joueur pour la semaine courante.
    Crée l'assignation au 1er appel de la semaine."""

    def __init__(
        self,
        player_repository: PlayerRepository,
        quest_repository: WeeklyQuestRepository,
    ) -> None:
        self.player_repository = player_repository
        self.quest_repository = quest_repository

    def execute(
        self,
        discord_id: int,
        username: str,
        display_name: str,
    ) -> WeeklyQuestState:
        profile = self.player_repository.get_or_create_by_discord_id(
            discord_id=discord_id, username=username, display_name=display_name,
        )
        week_start = get_current_week_start()

        if not self.quest_repository.has_assignments_for_week(
            profile.player.id, week_start
        ):
            picks = pick_random_assignment(count=3)
            self.quest_repository.assign(
                profile.player.id, week_start, [d.code for d in picks]
            )

        assignments = self.quest_repository.list_for_player_week(
            profile.player.id, week_start
        )

        statuses: list[QuestStatus] = []
        for a in assignments:
            d = get_definition(a.quest_code)
            if d is None:
                continue
            statuses.append(
                QuestStatus(
                    code=a.quest_code,
                    name=d.name,
                    description=d.description,
                    tier=d.tier,
                    progress=a.progress,
                    objective_quantity=d.objective_quantity,
                    completed=a.completed,
                    claimed=a.claimed,
                    reward_gold=d.reward_gold,
                    reward_xp=d.reward_xp,
                    reward_items=d.reward_items,
                )
            )
        return WeeklyQuestState(week_start=week_start, quests=statuses)


@dataclass
class ClaimResult:
    success: bool
    message: str
    gold: int = 0
    xp: int = 0
    items: list = field(default_factory=list)
    leveled_up: bool = False
    new_level: int | None = None


class ClaimWeeklyQuestUseCase:
    """Valide une quête complétée et distribue les récompenses au joueur."""

    def __init__(
        self,
        player_repository: PlayerRepository,
        quest_repository: WeeklyQuestRepository,
        item_repository: ItemRepository,
        inventory_repository: InventoryRepository,
        progression_service: ProgressionService | None = None,
    ) -> None:
        self.player_repository = player_repository
        self.quest_repository = quest_repository
        self.item_repository = item_repository
        self.inventory_repository = inventory_repository
        self.progression_service = progression_service or ProgressionService()

    def execute(
        self,
        discord_id: int,
        username: str,
        display_name: str,
        quest_code: str,
    ) -> ClaimResult:
        profile = self.player_repository.get_or_create_by_discord_id(
            discord_id=discord_id, username=username, display_name=display_name,
        )
        week_start = get_current_week_start()

        d = get_definition(quest_code)
        if d is None:
            return ClaimResult(
                success=False, message=f"❌ Quête `{quest_code}` introuvable."
            )

        assignment = self.quest_repository.get_assignment(
            profile.player.id, week_start, quest_code
        )
        if assignment is None:
            return ClaimResult(
                success=False,
                message="❌ Cette quête ne fait pas partie de votre semaine.",
            )
        if not assignment.completed:
            return ClaimResult(
                success=False,
                message=(
                    f"❌ Quête pas encore terminée : "
                    f"{assignment.progress}/{d.objective_quantity}."
                ),
            )
        if assignment.claimed:
            return ClaimResult(
                success=False, message="⚠️ Récompense déjà réclamée."
            )

        # Appliquer les récompenses
        self.player_repository.add_gold(profile.player.id, d.reward_gold)

        new_level, new_xp, new_skill_points = self.progression_service.apply_level_up(
            current_level=profile.progression.level,
            current_xp=profile.progression.xp,
            gained_xp=d.reward_xp,
            current_skill_points=profile.progression.skill_points,
        )
        leveled = new_level > profile.progression.level
        self.player_repository.apply_progression(
            player_id=profile.player.id,
            new_level=new_level,
            new_xp=new_xp,
            new_skill_points=new_skill_points,
        )

        for item_code, qty in d.reward_items:
            item = self.item_repository.get_by_code(item_code)
            if item is None:
                continue
            self.inventory_repository.add_item(
                player_id=profile.player.id, item_definition_id=item.id, quantity=int(qty),
            )

        self.quest_repository.mark_claimed(profile.player.id, week_start, quest_code)

        return ClaimResult(
            success=True,
            message=f"✅ Récompense réclamée pour **{d.name}**.",
            gold=d.reward_gold,
            xp=d.reward_xp,
            items=list(d.reward_items),
            leveled_up=leveled,
            new_level=new_level if leveled else None,
        )


class WeeklyQuestProgressService:
    """Service utilitaire à appeler après chaque évènement de jeu pertinent.

    Centralisé pour ne pas redupliquer la logique. Chaque évènement résout
    le `objective_type` matchant et incrémente toutes les quêtes assignées
    actives sur la semaine courante.
    """

    def __init__(self, quest_repository: WeeklyQuestRepository) -> None:
        self.quest_repository = quest_repository

    def _process_event(
        self,
        player_id: int,
        objective_type: str,
        amount: int,
        target_filter: str | None = None,
    ) -> None:
        """Pour chaque définition matchant le type (et target si pertinent),
        si le joueur a une assignation active cette semaine, incrémenter."""
        if amount <= 0:
            return
        week_start = get_current_week_start()
        candidates: list[WeeklyQuestDefinition] = list_for_objective_type(objective_type)
        if target_filter is not None:
            candidates = [d for d in candidates if d.objective_target == target_filter]

        for d in candidates:
            self.quest_repository.add_progress(
                player_id=player_id,
                week_start=week_start,
                quest_code=d.code,
                amount=amount,
                objective_quantity=d.objective_quantity,
            )

    # ---------- API événementielle (1 méthode par hook) ----------

    def on_kill(self, player_id: int, family: str, count: int = 1) -> None:
        self._process_event(player_id, "kill_total", count)
        if family:
            self._process_event(player_id, "kill_family", count, target_filter=family)

    def on_duel_won(self, player_id: int, count: int = 1) -> None:
        self._process_event(player_id, "duel_win", count)

    def on_craft(self, player_id: int, count: int = 1) -> None:
        self._process_event(player_id, "craft_any", count)

    def on_gather(self, player_id: int, count: int = 1) -> None:
        self._process_event(player_id, "gather_count", count)

    def on_gold_earned(self, player_id: int, amount: int) -> None:
        self._process_event(player_id, "gold_earned", amount)

    def on_boss_damage(self, player_id: int, damage: int) -> None:
        self._process_event(player_id, "boss_damage", damage)

    def on_daily_claimed(self, player_id: int, current_streak: int) -> None:
        """daily_streak utilise set_progress_at_least (atteindre N, pas
        cumuler). On loop sur les définitions matchantes."""
        if current_streak <= 0:
            return
        week_start = get_current_week_start()
        for d in list_for_objective_type("daily_streak"):
            self.quest_repository.set_progress_at_least(
                player_id=player_id,
                week_start=week_start,
                quest_code=d.code,
                value=current_streak,
                objective_quantity=d.objective_quantity,
            )
