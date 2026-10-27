"""Offrande commune : dons, remplissage une fois par jour, dépassement reporté,
bénédiction (base SQLite réelle)."""

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


def test_le_depassement_passe_dans_la_jauge_suivante(session):
    pid = _player(session, gold=10_000)
    first = offering.contribute(session, _profile(session), 1_000, NOW)
    assert first.given == 1_000 and first.invoked is None and _gold(session, pid) == 9_000
    full = offering.contribute(session, _profile(session), 2_000, NOW)
    assert full.given == 2_000 and full.invoked is not None and _gold(session, pid) == 7_000
    assert offering.active_blessing(session, NOW).code == full.invoked.code
    assert offering.active_blessing(session, NOW + timedelta(hours=25)) is None
    nxt = full.status
    assert not nxt.open and nxt.target == osvc.grown(osvc.BASE_TARGET, 1)
    assert nxt.contributed == 3_000 - osvc.BASE_TARGET and nxt.mine == 1_500   # le dépassement est à lui


def test_une_fois_par_jour_les_dons_d_avance_s_exaucent_a_minuit(session):
    _player(session, gold=100_000)
    offering.contribute(session, _profile(session), osvc.BASE_TARGET, NOW)
    later = offering.contribute(session, _profile(session), 5_000, NOW + timedelta(hours=2))
    assert later.invoked is None and later.status.contributed == 5_000      # prépare la suivante
    assert offering.release(session, NOW + timedelta(hours=3)) is None        # pas deux fois le même jour
    tomorrow = NOW + timedelta(days=1)
    invoked = offering.release(session, tomorrow)
    state = offering.status(session, None, tomorrow)
    assert invoked is not None and state.fills == 2 and not state.open
    assert state.contributed == 5_000 - osvc.grown(osvc.BASE_TARGET, 1)


def test_le_prix_redescend_de_chaque_jour_sans_remplissage(session):
    session.add(OfferingStateModel(id=1, cycle=5, target=60_000, contributed=0, fills=4,
                                   filled_on=NOW.date(), priced_on=NOW.date()))
    session.commit()
    # Le jour du remplissage ne compte pas ; les trois suivants, oui.
    assert offering.status(session, None, NOW + timedelta(days=4)).target == osvc.decayed(60_000, 3) == 56_472


def test_on_ne_donne_pas_plus_que_son_or(session):
    _player(session, gold=0)
    with pytest.raises(offering.OfferingError, match="pas d'or"):
        offering.contribute(session, _profile(session), 1_000, NOW)


def test_la_benediction_de_thalos_donne_un_ticket_de_tour(session):
    pid = _player(session, gold=0)
    session.add(OfferingStateModel(id=1, cycle=2, target=1_638, contributed=0, fills=1,
                                   deity_code="thalos", blessed_at=NOW.replace(tzinfo=None),
                                   blessing_until=(NOW + timedelta(hours=24)).replace(tzinfo=None)))
    session.commit()
    assert TowerTicketsUseCase(session).status(pid, NOW).allowance == 2
