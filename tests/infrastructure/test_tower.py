"""Tour solo : tickets, record permanent, récompenses (base SQLite réelle ;
le combat est simulé — son équilibre est testé dans tests/content)."""

from datetime import UTC, datetime

import pytest

from app.application.use_cases import tower
from app.domain.services import tower_service as ts
from app.domain.value_objects.party_battle_result import PartyBattleResult
from app.infrastructure.db.models.tower_progress_model import PlayerTowerProgressModel  # noqa: F401
from app.infrastructure.db.models.tower_ticket_model import PlayerTowerTicketModel  # noqa: F401
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from tests.infrastructure.test_merchant_tools import _player
from tests.infrastructure.test_unit_of_work import _gold
from tests.infrastructure.test_use_consumable import session  # noqa: F401

NOW = datetime(2026, 10, 27, 12, tzinfo=UTC)


def _result(victory: bool) -> PartyBattleResult:
    return PartyBattleResult(victory=victory, turns=12, mob_name="m", mob_image_name="",
                             mob_remaining_hp=0 if victory else 50, surviving_players=[],
                             defeated_players=[], xp_gained=0, gold_gained=0, summary="",
                             turn_logs=[], enemies=[{"code": "m", "name": "m", "max_hp": 100,
                                                     "remaining_hp": 0 if victory else 50,
                                                     "defeated": victory}])


@pytest.fixture
def fights(monkeypatch):
    """Issues des prochains combats (True = victoire)."""
    queue: list[bool] = []
    monkeypatch.setattr(tower, "_fight", lambda session, profile, floor: _result(queue.pop(0)))
    return queue


def _profile(session):
    return PlayerRepository(session).get_or_create_by_discord_id(1, "u", "U")


def test_on_garde_son_ticket_tant_qu_on_gagne(session, fights):
    pid = _player(session, gold=0, level=1)
    fights += [True, True, True]
    for floor in (1, 2, 3):
        outcome = tower.attempt(session, _profile(session), NOW)
        assert outcome.victory and outcome.floor == floor and not outcome.ticket_used
        assert outcome.tickets_left == 1
    assert tower.status(session, _profile(session), NOW).best_floor == 3
    expected = sum(ts.first_clear_reward(f).gold for f in (1, 2, 3))
    assert _gold(session, pid) == expected


def test_une_defaite_coute_le_ticket_jamais_un_etage(session, fights):
    _player(session, gold=0, level=1)
    fights += [True, False]
    tower.attempt(session, _profile(session), NOW)
    lost = tower.attempt(session, _profile(session), NOW)
    assert not lost.victory and lost.ticket_used and lost.tickets_left == 0 and lost.best_floor == 1
    with pytest.raises(tower.TowerError, match="Plus de ticket"):
        tower.attempt(session, _profile(session), NOW)
    tomorrow = datetime(2026, 10, 28, 12, tzinfo=UTC)
    fights.append(True)
    assert tower.attempt(session, _profile(session), tomorrow).floor == 2    # on reprend où on en était


def test_recompense_du_jour_une_fois_selon_le_record(session, fights):
    pid = _player(session, gold=0, level=1)
    with pytest.raises(tower.TowerError, match="au moins un étage"):
        tower.claim_daily(session, _profile(session), NOW)
    fights += [True, True]
    tower.attempt(session, _profile(session), NOW)
    tower.attempt(session, _profile(session), NOW)
    before = _gold(session, pid)
    reward = tower.claim_daily(session, _profile(session), NOW)
    assert reward.gold == ts.daily_reward(2).gold and _gold(session, pid) == before + reward.gold
    with pytest.raises(tower.TowerError, match="déjà prise"):
        tower.claim_daily(session, _profile(session), NOW)
