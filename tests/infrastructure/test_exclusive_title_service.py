"""Tests du ExclusiveTitleService — gestion des titres uniques (Champion
1v1, Farmer Fou). Vérifie l'attribution, le transfert, et le retrait."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.application.services.exclusive_title_service import ExclusiveTitleService
from app.infrastructure.db.base import Base
from app.infrastructure.db.models.player_model import PlayerModel
from app.infrastructure.db.models.player_title_model import PlayerTitleModel


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    try:
        yield s
    finally:
        s.close()
        engine.dispose()


def _create_player(session, name: str) -> int:
    now = datetime.now(UTC)
    p = PlayerModel(
        discord_id=hash(name) & 0xFFFFFFFF, username=name.lower(), display_name=name,
        created_at=now, updated_at=now,
    )
    session.add(p)
    session.flush()
    session.commit()
    return p.id


def test_award_to_creates_when_no_holder(session):
    p = _create_player(session, "Alice")
    service = ExclusiveTitleService(session)

    changed = service.award_to("champion_1v1", p)

    assert changed is True
    assert service.current_holder("champion_1v1") == p


def test_award_to_same_holder_is_no_op(session):
    p = _create_player(session, "Alice")
    service = ExclusiveTitleService(session)

    service.award_to("champion_1v1", p)
    changed = service.award_to("champion_1v1", p)

    assert changed is False
    assert service.current_holder("champion_1v1") == p


def test_award_to_transfers_from_old_holder(session):
    alice = _create_player(session, "Alice")
    bob = _create_player(session, "Bob")
    service = ExclusiveTitleService(session)

    service.award_to("champion_1v1", alice)
    changed = service.award_to("champion_1v1", bob)

    assert changed is True
    assert service.current_holder("champion_1v1") == bob

    # Alice n'a plus le titre du tout (la ligne est supprimée)
    rows = session.execute(
        select(PlayerTitleModel).where(
            PlayerTitleModel.player_id == alice,
            PlayerTitleModel.title_code == "champion_1v1",
        )
    ).scalars().all()
    assert rows == []


def test_award_to_revokes_active_status_too(session):
    """Si l'ancien détenteur avait défini le titre comme actif (visible
    dans /profile), la suppression de la ligne le retire automatiquement."""
    alice = _create_player(session, "Alice")
    bob = _create_player(session, "Bob")
    service = ExclusiveTitleService(session)

    service.award_to("champion_1v1", alice)
    # Alice marque le titre comme actif
    alice_title = session.execute(
        select(PlayerTitleModel).where(
            PlayerTitleModel.player_id == alice,
            PlayerTitleModel.title_code == "champion_1v1",
        )
    ).scalar_one()
    alice_title.is_active = True
    session.commit()

    # Bob prend le titre → Alice perd tout
    service.award_to("champion_1v1", bob)

    # Alice n'a plus aucun titre champion_1v1, même actif
    alice_rows = session.execute(
        select(PlayerTitleModel).where(
            PlayerTitleModel.player_id == alice,
        )
    ).scalars().all()
    assert alice_rows == []


def test_revoke_removes_all_holders(session):
    alice = _create_player(session, "Alice")
    service = ExclusiveTitleService(session)

    service.award_to("farmer_fou", alice)
    assert service.current_holder("farmer_fou") == alice

    revoked = service.revoke("farmer_fou")

    assert revoked is True
    assert service.current_holder("farmer_fou") is None


def test_revoke_returns_false_when_no_holder(session):
    service = ExclusiveTitleService(session)

    assert service.revoke("farmer_fou") is False


def test_award_to_does_not_affect_other_titles(session):
    """Donner champion_1v1 à Alice ne doit pas toucher son titre slime_slayer."""
    alice = _create_player(session, "Alice")
    bob = _create_player(session, "Bob")
    now = datetime.now(UTC)

    # Alice débloque slime_slayer (titre non exclusif classique)
    session.add(PlayerTitleModel(
        player_id=alice, title_code="slime_slayer",
        unlocked_at=now, is_active=True,
    ))
    session.commit()

    service = ExclusiveTitleService(session)
    service.award_to("champion_1v1", alice)
    service.award_to("champion_1v1", bob)  # Bob prend le titre

    # Alice garde son slime_slayer (avec is_active=True intact)
    slime = session.execute(
        select(PlayerTitleModel).where(
            PlayerTitleModel.player_id == alice,
            PlayerTitleModel.title_code == "slime_slayer",
        )
    ).scalar_one()
    assert slime.is_active is True
