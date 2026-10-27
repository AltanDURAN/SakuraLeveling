"""Défis de rôle (`/defi`) : un essai, les classements, la clôture de la semaine.

Règles pures dans `app/domain/services/role_trial_service.py`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from app.application.services.combat_passives_resolver import resolve_party_passives
from app.application.services.exclusive_title_service import ExclusiveTitleService
from app.application.services.player_stats_resolver import resolve_player_stats
from app.infrastructure.db.unit_of_work import atomic
from app.domain.entities.player_profile import PlayerProfile
from app.domain.services import role_trial_service as rts
from app.infrastructure.db.repositories.equipment_repository import EquipmentRepository
from app.infrastructure.db.repositories.player_career_stats_repository import (
    PlayerCareerStatsRepository,
)
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.repositories.role_trial_repository import RoleTrialRepository


@dataclass(frozen=True)
class AttemptOutcome:
    role: str
    variant: rts.TrialVariant
    score: int
    best: int               # meilleur score du jour (celui-ci compris)
    improved: bool          # nouveau record du jour
    attempts: int
    day_rank: int           # place du jour (1 = premier), sur `day_count`
    day_count: int
    actions: int
    survived: bool


def run_attempt(session: Session, profile: PlayerProfile, role: str, now: datetime) -> AttemptOutcome:
    """Joue un essai DÉTERMINISTE (même build ⇒ même score) et garde le
    meilleur score du jour. L'appelant vérifie `rts.is_closed(now)`."""
    player_id = profile.player.id
    day = rts.trial_day(now)
    variant = rts.variant_of_day(day, role)
    worn = EquipmentRepository(session).list_by_player_id(player_id)
    stats = resolve_player_stats(session, profile, worn)
    passives, tactics = resolve_party_passives(session, [player_id])
    run = rts.run_trial(
        role, variant, player_id=player_id, name=profile.player.display_name,
        stats=stats, passives=passives.get(player_id), tactic=tactics.get(player_id),
        seed=rts.attempt_seed(day, role, player_id),
    )
    repo = RoleTrialRepository(session)
    best, improved, attempts = repo.record(player_id, day, role, variant.code, run.score)
    if attempts == 1:   # défi RELEVÉ : le premier essai du rôle aujourd'hui
        _quest_hook(session, player_id, role)
    board = repo.day_scores(day, role)
    rank = next((i + 1 for i, (pid, _) in enumerate(board) if pid == player_id), len(board))
    return AttemptOutcome(role, variant, run.score, best, improved, attempts, rank,
                          len(board), run.actions, run.survived)


def _quest_hook(session: Session, player_id: int, role: str) -> None:
    """Quêtes « relever un défi » (quotidienne et hebdo) — au mieux."""
    import logging

    try:
        from app.application.use_cases.daily_quests import DailyQuestProgressService
        from app.application.use_cases.weekly_quests import WeeklyQuestProgressService
        from app.infrastructure.db.repositories.daily_quest_repository import DailyQuestRepository
        from app.infrastructure.db.repositories.weekly_quest_repository import WeeklyQuestRepository

        DailyQuestProgressService(DailyQuestRepository(session)).on_role_trial(player_id, role)
        WeeklyQuestProgressService(WeeklyQuestRepository(session)).on_role_trial(player_id, role)
    except Exception:  # noqa: BLE001 — une quête ne doit jamais bloquer un défi
        logging.getLogger(__name__).warning("quest hook (défi) failed", exc_info=True)


@dataclass(frozen=True)
class WeekStandings:
    week_start: date
    roles: dict[str, list[tuple[int, float]]]   # rôle → (player_id, score), du 1er au dernier
    general: list[tuple[int, float]]


def week_standings(session: Session, week: date) -> WeekStandings:
    """Classements de la semaine qui commence le lundi `week` (en cours ou finie)."""
    rows = RoleTrialRepository(session).week_rows(week, week + timedelta(days=6))
    weekly = rts.weekly_scores(rows)
    return WeekStandings(
        week_start=week,
        roles={role: rts.ranking(weekly[role]) for role in rts.ROLES},
        general=rts.ranking(rts.general_scores(weekly)),
    )


def player_week(standings: WeekStandings, player_id: int) -> dict[str, tuple[int, float] | None]:
    """{rôle ou « general »: (place, score)} du joueur, None s'il n'y figure pas."""
    out: dict[str, tuple[int, float] | None] = {}
    for key, board in [*standings.roles.items(), (rts.GENERAL, standings.general)]:
        out[key] = next(((i + 1, s) for i, (pid, s) in enumerate(board) if pid == player_id), None)
    return out


def settle_week(session: Session, week: date) -> dict | None:
    """Clôture la semaine : or du podium de chaque classement et titres de la
    semaine. Idempotent — None si déjà clôturée. Renvoie les résultats
    {clé: [{player_id, name, score, gold}]} pour l'annonce."""
    # Or du podium et titres : tout ou rien (unit_of_work).
    with atomic(session):
        repo = RoleTrialRepository(session)
        if repo.is_settled(week):
            return None
        standings = week_standings(session, week)
        players = PlayerRepository(session)
        career = PlayerCareerStatsRepository(session)

        results: dict[str, list[dict]] = {}
        payouts: list[tuple[int, int]] = []
        for key, board in [*standings.roles.items(), (rts.GENERAL, standings.general)]:
            podium = []
            for place, (pid, score) in enumerate(board[:len(rts.REWARD_GOLD_PER_LEVEL)]):
                profile = players.get_profile_by_player_id(pid)
                if profile is None:
                    continue
                gold = rts.reward_gold(place, profile.progression.level)
                payouts.append((pid, gold))
                podium.append({"player_id": pid, "discord_id": profile.player.discord_id,
                               "name": profile.player.display_name, "score": score, "gold": gold})
            results[key] = podium

        repo.mark_settled(week, results)
        for pid, gold in payouts:
            if gold > 0:
                players.add_gold(pid, gold)
                career.add(pid, gold_earned=gold)

        titles = ExclusiveTitleService(session)
        for key, code in rts.WEEKLY_TITLES.items():
            podium = results.get(key) or []
            if podium:
                titles.award_to(code, podium[0]["player_id"])
            else:
                titles.revoke(code)   # personne cette semaine : le titre retombe
        return results
