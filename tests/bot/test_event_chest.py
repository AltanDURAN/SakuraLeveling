"""Un coffre au trésor que personne n'ouvre disparaît au bout de
`expire_after_minutes` (24 h par défaut) et laisse place au suivant.
Constaté le 10/11/2026 : un coffre du 24/08 n'avait jamais été ouvert, et
aucun autre n'était paru depuis (un seul coffre actif à la fois)."""

import asyncio
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.bot.cogs import event_cog
from app.infrastructure.db.base import Base
from app.infrastructure.db.models.event_model import ActiveEventModel
from app.infrastructure.db.repositories.event_repository import EventRepository
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.events import event_config_loader as cfg


@pytest.fixture
def db(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)

    @contextmanager
    def get_session():
        s = factory()
        try:
            yield s
        finally:
            s.close()

    monkeypatch.setattr(event_cog, "get_db_session", get_session)
    cfg.clear_cache()
    yield get_session
    engine.dispose()


class _Message:
    attachments: list = []

    def __init__(self):
        self.edits = []

    async def edit(self, **kwargs):
        self.edits.append(kwargs)


class _Bot:
    def __init__(self):
        self.message = _Message()

    def get_channel(self, channel_id):
        message = self.message

        class _Channel:
            async def fetch_message(self, message_id):
                return message
        return _Channel()


def _cog(bot):
    cog = event_cog.EventCog.__new__(event_cog.EventCog)   # sans démarrer ses boucles
    cog.bot = bot
    return cog


def _chest(get_session, age: timedelta) -> int:
    with get_session() as s:
        repo = EventRepository(s)
        ev = repo.create("chest", 111)
        ev.created_at = datetime.now(UTC).replace(tzinfo=None) - age
        ev.message_id = 999
        s.commit()
        return ev.id


def _status(get_session, event_id):
    with get_session() as s:
        return s.get(ActiveEventModel, event_id).status


def test_un_coffre_oublie_disparait_et_laisse_place_au_suivant(db):
    bot = _Bot()
    event_id = _chest(db, timedelta(days=78))
    asyncio.run(_cog(bot)._expire_stale_chest())
    assert _status(db, event_id) == "expired"
    edit = bot.message.edits[0]
    assert "volatilisé" in edit["embed"].title and edit["view"] is None
    with db() as s:
        assert EventRepository(s).get_active_by_type("chest") is None     # le suivant peut paraître


def test_un_coffre_recent_reste_la(db):
    bot = _Bot()
    event_id = _chest(db, timedelta(hours=23))
    asyncio.run(_cog(bot)._expire_stale_chest())
    assert _status(db, event_id) == "active" and not bot.message.edits


def test_ouvert_ou_expire_jamais_les_deux(db):
    with db() as s:
        pid = PlayerRepository(s).get_or_create_by_discord_id(7, "alice", "Alice").player.id
        s.commit()
    opened = _chest(db, timedelta(days=2))
    with db() as s:
        repo = EventRepository(s)
        assert repo.claim_chest_winner(opened, pid)
        assert not repo.expire_unclaimed(opened)          # déjà ouvert : rien à faire
    assert _status(db, opened) == "resolved"
    gone = _chest(db, timedelta(days=2))
    with db() as s:
        repo = EventRepository(s)
        assert repo.expire_unclaimed(gone)
        assert not repo.claim_chest_winner(gone, pid)      # volatilisé : trop tard
