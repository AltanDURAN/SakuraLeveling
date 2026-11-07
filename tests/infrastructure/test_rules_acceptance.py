"""Règlement accepté (07/11/2026) : par compte Discord, une fois par version,
journalisé pour la surveillance."""

from sqlalchemy import select

from app.application.use_cases import rules
from app.infrastructure.db.models.monitoring_model import GameEventModel
from tests.infrastructure.test_encounter_service import (  # noqa: F401  (fixtures)
    _create_player,
    session,
)


def test_accepter_une_fois_par_version(session):
    assert rules.acceptance(session, 42) is None
    assert rules.accept(session, 42, 1)
    first = rules.acceptance(session, 42)
    assert first.version == 1
    assert not rules.accept(session, 42, 1)                 # déjà acceptée : rien ne change
    assert rules.acceptance(session, 42).accepted_at == first.accepted_at
    assert rules.accept(session, 42, 2)                     # nouvelle version importante
    assert rules.acceptance(session, 42).version == 2
    assert not rules.accept(session, 42, 1)                 # jamais de retour en arrière
    assert rules.acceptance(session, 42).version == 2


def test_on_accepte_avant_d_avoir_un_personnage_et_c_est_journalise(session):
    rules.accept(session, 7, 1)                             # pas encore de joueur
    pid = _create_player(session, discord_id=8, name="Alice")
    rules.accept(session, 8, 1)
    events = session.execute(select(GameEventModel).where(GameEventModel.kind == "rules")
                             .order_by(GameEventModel.id)).scalars().all()
    assert [(e.discord_id, e.player_id, e.qty) for e in events] == [(7, None, 1), (8, pid, 1)]
