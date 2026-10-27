"""Offrande commune : dons, remplissage une fois par jour, bénédiction
(base SQLite réelle)."""

from datetime import UTC, datetime, timedelta

import pytest

from app.application.use_cases import offering
from app.application.use_cases.tower_tickets import TowerTicketsUseCase
from app.domain.services import offering_service as osvc
from app.infrastructure.db.models.offering_model import OfferingStateModel
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from tests.infrastructure.test_merchant_tools import _player
from tests.infrastructure.test_unit_of_work import _gold
from tests.infrastructure.test_use_consumable import session  # noqa: F401

NOW = datetime(2026, 10, 27, 12, tzinfo=UTC)


def _profile(session):
    return PlayerRepository(session).get_or_create_by_discord_id(1, "u", "U")


def test_un_don_ne_prend_que_ce_qui_manque_et_invoque_une_divinite(session):
    pid = _player(session, gold=100_000)
    first = offering.contribute(session, _profile(session), 10_000, NOW)
    assert first.given == 10_000 and first.invoked is None and _gold(session, pid) == 90_000
    full = offering.contribute(session, _profile(session), 90_000, NOW)
    assert full.given == osvc.BASE_TARGET - 10_000 and full.invoked is not None
    assert _gold(session, pid) == 100_000 - osvc.BASE_TARGET
    assert offering.active_blessing(session, NOW).code == full.invoked.code
    assert offering.active_blessing(session, NOW + timedelta(hours=25)) is None
    assert full.status.target == osvc.grown(osvc.BASE_TARGET) and not full.status.open


def test_une_seule_fois_par_jour_et_le_prix_redescend_sans_remplissage(session):
    _player(session, gold=1_000_000)
    offering.contribute(session, _profile(session), osvc.BASE_TARGET, NOW)
    with pytest.raises(offering.OfferingError, match="déjà été exaucée"):
        offering.contribute(session, _profile(session), 1_000, NOW + timedelta(hours=2))
    tomorrow = NOW + timedelta(days=1)
    assert offering.status(session, None, tomorrow).target == osvc.grown(osvc.BASE_TARGET)


def test_le_prix_redescend_de_chaque_jour_sans_remplissage(session):
    session.add(OfferingStateModel(id=1, cycle=5, target=60_000, contributed=0, fills=4,
                                   filled_on=NOW.date(), priced_on=NOW.date()))
    session.commit()
    # Le jour du remplissage ne compte pas ; les trois suivants, oui.
    assert offering.status(session, None, NOW + timedelta(days=4)).target == osvc.decayed(60_000, 3) == 51_500


def test_la_benediction_de_thalos_donne_un_ticket_de_tour(session, monkeypatch):
    pid = _player(session, gold=0)
    session.add(OfferingStateModel(id=1, cycle=2, target=27_000, contributed=0, fills=1,
                                   deity_code="thalos", blessed_at=NOW.replace(tzinfo=None),
                                   blessing_until=(NOW + timedelta(hours=24)).replace(tzinfo=None)))
    session.commit()
    assert TowerTicketsUseCase(session).status(pid, NOW).allowance == 2
