"""Papier élémentaire de bout en bout, via le VRAI dispatch de discord.py.

`View._scheduled_task` appelle `item._run_checks` avant le callback : c'est là
qu'un composant qui écrase un attribut interne de discord.py (`_parent`,
depuis la 2.6) plante — le joueur clique et rien ne se passe. Appeler les
callbacks directement ne l'aurait pas vu.
"""

import asyncio
from contextlib import contextmanager
from datetime import datetime, UTC
from types import SimpleNamespace

import discord
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.bot.views import element_paper_view as epv
from app.infrastructure.db.base import Base
from app.infrastructure.db.models.element_affinity_model import (  # noqa: F401
    PlayerElementAffinityModel,
)
from app.infrastructure.db.models.element_essence_model import (  # noqa: F401
    PlayerElementEssenceModel,
)
from app.infrastructure.db.models.player_model import PlayerModel
from app.infrastructure.db.models.progression_model import PlayerProgressionModel
from app.infrastructure.db.models.resource_model import PlayerResourceModel


class FakeResponse:
    def __init__(self):
        self.calls = []

    async def send_message(self, *args, **kwargs):
        self.calls.append(("send", args, kwargs))

    async def edit_message(self, *args, **kwargs):
        self.calls.append(("edit", args, kwargs))

    async def defer(self, *args, **kwargs):
        self.calls.append(("defer", args, kwargs))


def fake_interaction(user_id=1, values=None):
    return SimpleNamespace(
        user=SimpleNamespace(id=user_id),
        response=FakeResponse(),
        data={"values": values or []},
    )


@pytest.fixture
def session_factory(monkeypatch):
    # Une seule connexion partagée : les vues passent par asyncio.to_thread.
    engine = create_engine(
        "sqlite:///:memory:", poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine, tables=[
        PlayerModel.__table__, PlayerProgressionModel.__table__,
        PlayerResourceModel.__table__, PlayerElementAffinityModel.__table__,
        PlayerElementEssenceModel.__table__,
    ])
    maker = sessionmaker(bind=engine)
    with maker() as s:
        now = datetime.now(UTC)
        p = PlayerModel(id=1, discord_id=1, username="u", display_name="U",
                        created_at=now, updated_at=now, last_seen_at=now)
        p.progression = PlayerProgressionModel(level=1, xp=0, skill_points=0,
                                               created_at=now, updated_at=now)
        p.resources = PlayerResourceModel(gold=1000, created_at=now, updated_at=now)
        s.add(p)
        s.commit()
    monkeypatch.setattr(epv, "_prices", lambda: (0, 500, 900, 1, 1, 1, 1, 1))

    @contextmanager
    def factory():
        with maker() as s:
            yield s
    return factory


async def _dispatch(view, item, interaction):
    """Ce que discord.py fait quand un joueur clique."""
    if isinstance(item, discord.ui.Select):
        item._refresh_state(interaction, interaction.data)
    await view._scheduled_task(item, interaction)


def _item(view, cls):
    return next(c for c in view.children if isinstance(c, cls))


def test_parcours_complet_papier(session_factory):
    async def run():
        status = epv.load_status(session_factory, 1)
        view = epv.ElementPaperView(session_factory, 1, status)

        # 1. choisir l'élément
        inter = fake_interaction(values=["feu"])
        await _dispatch(view, _item(view, epv._ElementSelect), inter)
        assert inter.response.calls and inter.response.calls[0][0] == "edit"
        assert view.element == "feu"

        # 2. lire le papier (offert)
        button = _item(view, epv._ReadButton)
        assert not button.disabled
        inter = fake_interaction()
        await _dispatch(view, button, inter)
        kind, _, kwargs = inter.response.calls[0]
        assert kind == "edit" and "Ton talent" in kwargs["embed"].title

        status = epv.load_status(session_factory, 1)
        assert "feu" in status.revealed and status.next_price == 500
    asyncio.run(run())


def test_bouton_papier_refuse_un_autre_joueur(session_factory):
    async def run():
        view = discord.ui.View()
        button = epv.PaperButton(session_factory, 1, 0, owner_discord_id=1)
        view.add_item(button)
        inter = fake_interaction(user_id=2)
        await _dispatch(view, button, inter)
        kind, args, kwargs = inter.response.calls[0]
        assert kind == "send" and kwargs.get("ephemeral")
        assert "pas pour toi" in args[0]

        inter = fake_interaction(user_id=1)
        await _dispatch(view, button, inter)
        kind, _, kwargs = inter.response.calls[0]
        assert kind == "send" and isinstance(kwargs["view"], epv.ElementPaperView)
    asyncio.run(run())
