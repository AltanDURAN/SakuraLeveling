"""Tickets de la tour solo : quota du jour, non cumulable."""

from datetime import datetime, UTC

from app.application.use_cases.tower_tickets import TowerTicketsUseCase, daily_allowance
from app.infrastructure.db.models.tower_ticket_model import PlayerTowerTicketModel  # noqa: F401
from tests.infrastructure.test_reset_player_use_case import _create_player, session  # noqa: F401

DAY1 = datetime(2026, 10, 20, 12, tzinfo=UTC)
DAY2 = datetime(2026, 10, 21, 9, tzinfo=UTC)


def test_quota_de_base_et_bonus():
    assert daily_allowance(set()) == 1
    assert daily_allowance({"tower_bonus_ticket"}) == 2


def test_un_ticket_par_jour_sans_report(session):
    pid = _create_player(session, 1, "Alice")
    uc = TowerTicketsUseCase(session)
    assert uc.status(pid, DAY1).available == 1
    assert uc.consume(pid, DAY1)
    assert not uc.consume(pid, DAY1)
    assert uc.status(pid, DAY1).available == 0
    # Le lendemain : de nouveau 1, jamais 2 (pas de report).
    assert uc.status(pid, DAY2).available == 1


def test_un_jour_non_utilise_ne_s_accumule_pas(session):
    pid = _create_player(session, 1, "Alice")
    uc = TowerTicketsUseCase(session)
    assert uc.status(pid, DAY2).available == 1  # rien utilisé la veille → toujours 1
