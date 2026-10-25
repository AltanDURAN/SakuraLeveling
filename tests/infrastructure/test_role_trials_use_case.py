"""Défis de rôle de bout en bout (base en mémoire) : un essai, le record du
jour, la clôture de la semaine (or du podium, titres) et son idempotence."""

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application.services.exclusive_title_service import ExclusiveTitleService
from app.application.use_cases import role_trials
from app.domain.services import role_trial_service as rts
from app.infrastructure.db.base import Base
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.repositories.role_trial_repository import RoleTrialRepository

NOW = datetime(2026, 10, 21, 12, 0, tzinfo=UTC)   # mercredi
WEEK = date(2026, 10, 19)


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()
        engine.dispose()


def _player(session, discord_id, level=20, points_attack=0):
    from app.infrastructure.db.models.progression_model import PlayerProgressionModel

    repo = PlayerRepository(session)
    profile = repo.get_or_create_by_discord_id(
        discord_id=discord_id, username=f"u{discord_id}", display_name=f"Joueur {discord_id}")
    session.query(PlayerProgressionModel).filter_by(player_id=profile.player.id).update(
        {"level": level, "points_attack": points_attack})
    session.commit()
    return repo.get_profile_by_player_id(profile.player.id)


def test_un_essai_est_enregistre_et_rejouer_le_meme_build_ne_change_rien(session):
    profile = _player(session, 1, points_attack=10)
    first = role_trials.run_attempt(session, profile, "dps", NOW)
    again = role_trials.run_attempt(session, profile, "dps", NOW)
    assert first.score > 0 and first.improved and first.attempts == 1
    assert again.score == first.score and not again.improved and again.attempts == 2
    assert RoleTrialRepository(session).player_day(profile.player.id, rts.trial_day(NOW)) == {
        "dps": (first.score, 2)}


def test_le_meilleur_score_du_jour_est_garde(session):
    profile = _player(session, 1)
    repo = RoleTrialRepository(session)
    day = rts.trial_day(NOW)
    repo.record(profile.player.id, day, "tank", "classique", 500)
    best, improved, attempts = repo.record(profile.player.id, day, "tank", "classique", 300)
    assert (best, improved, attempts) == (500, False, 2)
    assert repo.record(profile.player.id, day, "tank", "classique", 900) == (900, True, 3)


def test_cloture_or_du_podium_titres_et_idempotence(session):
    alice, bob = _player(session, 1, level=40), _player(session, 2, level=10)
    repo = RoleTrialRepository(session)
    for offset in range(3):
        day = WEEK + timedelta(days=offset)
        repo.record(alice.player.id, day, "dps", "classique", 1000)
        repo.record(bob.player.id, day, "dps", "classique", 400)
        repo.record(bob.player.id, day, "soutien", "classique", 200)
    session.commit()
    gold_before = {p: PlayerRepository(session).get_profile_by_player_id(p).resources.gold
                   for p in (alice.player.id, bob.player.id)}

    results = role_trials.settle_week(session, WEEK)
    assert [e["player_id"] for e in results["dps"]] == [alice.player.id, bob.player.id]
    assert [e["player_id"] for e in results["soutien"]] == [bob.player.id]
    assert results["tank"] == []

    titles = ExclusiveTitleService(session)
    assert titles.current_holder("fleau_semaine") == alice.player.id
    assert titles.current_holder("ange_gardien_semaine") == bob.player.id
    assert titles.current_holder("bastion_semaine") is None
    # Général : Alice 100/3 (DPS) contre Bob (40 + 100)/3 → Bob premier.
    assert titles.current_holder("champion_semaine") == bob.player.id

    gold_after = {p: PlayerRepository(session).get_profile_by_player_id(p).resources.gold
                  for p in (alice.player.id, bob.player.id)}
    # Alice : 1re DPS (100 × 40) + 2e générale (60 × 40) ; Bob : 2e DPS, 1er soutien,
    # 1er général (60 + 100 + 100) × 10.
    assert gold_after[alice.player.id] - gold_before[alice.player.id] == 100 * 40 + 60 * 40
    assert gold_after[bob.player.id] - gold_before[bob.player.id] == (60 + 100 + 100) * 10

    assert role_trials.settle_week(session, WEEK) is None   # déjà clôturée : rien de plus
    assert PlayerRepository(session).get_profile_by_player_id(
        alice.player.id).resources.gold == gold_after[alice.player.id]


def test_semaine_sans_joueur_le_titre_retombe(session):
    alice = _player(session, 1)
    ExclusiveTitleService(session).award_to("bastion_semaine", alice.player.id)
    results = role_trials.settle_week(session, WEEK)
    assert not any(results.values())
    assert ExclusiveTitleService(session).current_holder("bastion_semaine") is None


def test_classement_de_la_semaine_en_cours(session):
    from app.application.use_cases.get_leaderboard import GetLeaderboardUseCase
    from app.domain.services.leaderboard_service import LeaderboardService
    from app.domain.services.power_score_service import PowerScoreService
    from app.domain.services.stats_service import StatsService
    from app.infrastructure.db.repositories.equipment_repository import EquipmentRepository
    from app.infrastructure.db.repositories.mob_repository import MobRepository
    from app.infrastructure.db.repositories.player_kill_repository import PlayerKillRepository

    alice = _player(session, 1)
    repo = RoleTrialRepository(session)
    repo.record(alice.player.id, rts.trial_day(datetime.now(UTC)), "tank", "classique", 4321)
    board = GetLeaderboardUseCase(
        PlayerRepository(session), EquipmentRepository(session), PlayerKillRepository(session),
        MobRepository(session), StatsService(), PowerScoreService(), LeaderboardService(),
        role_trial_repository=repo,
    ).execute("defi_tank")
    assert [(e.player_id, e.formatted_value) for e in board.entries] == [(alice.player.id, "4 321")]
