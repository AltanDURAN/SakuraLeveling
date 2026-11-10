"""Événements saisonniers côté bot : boutons utiles selon la date, annonces
postées UNE fois dans le salon des événements (@everyone au Nouvel An),
panneau épinglé tenu à jour, écrans et image du calendrier."""

import asyncio
import json
from contextlib import contextmanager
from datetime import date, datetime
from types import SimpleNamespace

import discord
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.application.use_cases.seasonal import AdventStatus
from app.bot.cogs import seasonal_cog
from app.bot.embeds import seasonal_embeds as se
from app.bot.rendering.advent_calendar import render_advent
from app.domain.services import seasonal_service as ss
from app.infrastructure.db.base import Base
from app.infrastructure.seasonal import seasonal_loader
from tests.domain.test_seasonal_service import RAW


def _paris(y, m, d, h=12):
    return datetime(y, m, d, h, tzinfo=ss.PARIS)


@pytest.fixture
def content(tmp_path, monkeypatch):
    path = tmp_path / "seasonal_events.json"
    path.write_text(json.dumps(RAW), encoding="utf-8")
    monkeypatch.setattr(seasonal_loader, "CONTENT_PATH", path)
    seasonal_loader.clear_cache()
    yield seasonal_loader.get_content()
    seasonal_loader.clear_cache()


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

    monkeypatch.setattr(seasonal_cog, "get_db_session", get_session)
    yield get_session
    engine.dispose()


class _Message:
    _ids = iter(range(1000, 9999))

    def __init__(self, channel, **kwargs):
        self.id = next(self._ids)
        self.channel = channel
        self.kwargs = kwargs
        self.embeds = [kwargs["embed"]] if kwargs.get("embed") else []
        self.pinned = False
        self.edits = []

    async def pin(self, reason=None):
        self.pinned = True

    async def edit(self, **kwargs):
        self.edits.append(kwargs)
        if kwargs.get("embed"):
            self.embeds = [kwargs["embed"]]


class _Channel:
    id = 4242

    def __init__(self):
        self.sent: list[_Message] = []

    async def send(self, **kwargs):
        message = _Message(self, **kwargs)
        self.sent.append(message)
        return message

    async def fetch_message(self, message_id):
        for m in self.sent:
            if m.id == message_id:
                return m
        raise discord.NotFound(SimpleNamespace(status=404, reason="Not Found"), "inconnu")

    def history(self, limit=5):
        async def _empty():
            for _ in ():
                yield _
        return _empty()


def _cog():
    cog = seasonal_cog.SeasonalCog.__new__(seasonal_cog.SeasonalCog)     # sans boucle
    cog.bot = SimpleNamespace(user=SimpleNamespace(id=1))
    cog._signature = None
    cog._panel_checked = None
    return cog


def test_les_boutons_du_panneau_suivent_le_calendrier(content):
    assert seasonal_cog.panel_buttons(content, _paris(2026, 11, 20)) == (("advent", "gift", "shop"),
                                                                         "L'atelier des lutins")
    assert seasonal_cog.panel_buttons(content, _paris(2026, 12, 26))[0] == ("gift", "shop")
    assert seasonal_cog.panel_buttons(content, _paris(2027, 1, 2))[0] == ()
    assert seasonal_cog.pick_shop(content, date(2026, 12, 26)).code == "lutins"


def test_chaque_annonce_part_une_seule_fois(content, db):
    cog, channel = _cog(), _Channel()
    posted = asyncio.run(cog.post_announcements(channel, content, _paris(2026, 12, 1, 0)))
    assert posted == ["advent:2026-12-01"] and "ouvert" in channel.sent[0].embeds[0].title
    assert isinstance(channel.sent[0].kwargs["view"], discord.ui.View)
    assert asyncio.run(cog.post_announcements(channel, content, _paris(2026, 12, 2))) == []
    new_year = asyncio.run(cog.post_announcements(channel, content, _paris(2027, 1, 1, 0)))
    assert new_year == ["new_year:2027-01-01"]
    sent = channel.sent[-1]
    assert sent.kwargs["content"] == "@everyone" and "view" not in sent.kwargs
    assert "Aurélia" in sent.embeds[0].description and "Thalos" in sent.embeds[0].description


def test_le_panneau_est_poste_epingle_puis_reecrit_quand_tout_change(content, db):
    cog, channel = _cog(), _Channel()
    assert asyncio.run(cog.keep_panel(channel, content, _paris(2026, 11, 20))) == "posté"
    panel = channel.sent[0]
    assert panel.pinned and panel.embeds[0].footer.text == se.PANEL_FOOTER
    assert "À venir" in [f.name for f in panel.embeds[0].fields][0]
    assert asyncio.run(cog.keep_panel(channel, content, _paris(2026, 11, 20, 13))) == "inchangé"
    assert asyncio.run(cog.keep_panel(channel, content, _paris(2026, 12, 1, 9))) == "mis à jour"
    assert "case **1**" in panel.embeds[0].description and len(channel.sent) == 1


def test_les_ecrans_prives(content):
    advent = content.advent
    today = date(2026, 12, 3)
    status = AdventStatus(advent, 3, frozenset({1}), tuple(ss.door_states(advent, today, {1})), 5, {})
    embed = se.build_advent_embed(status, "Alice")
    assert "case **3**" in embed.description and embed.footer.text.endswith("1 / 24 cases ouvertes")
    assert render_advent(status, "Alice")[:4] == b"\x89PNG"
    panel = se.build_panel_embed(content, ss.happening(content, _paris(2026, 12, 20)))
    assert "Sucres d'orge" in panel.description and "case **20**" in panel.description


def _texts(embed) -> str:
    parts = [embed.title or "", embed.description or "", embed.footer.text or ""]
    parts += [f"{f.name} {f.value}" for f in embed.fields]
    return " ".join(parts).lower()


def test_aucun_texte_ne_trahit_le_secret_de_la_petite_fille(content, monkeypatch):
    """Décision de l'auteur (10/11/2026) : les joueurs ne doivent pas savoir que
    le cadeau de Noël dépend de leurs choix face à la petite fille — ils
    l'aideraient pour ça. Avant Noël, rien ne laisse même entendre que le
    cadeau dépend de quoi que ce soit."""
    from pathlib import Path

    from app.application.use_cases.seasonal import ChristmasStatus

    c = content.christmas
    seen = []
    for day in (_paris(2026, 11, 20), _paris(2026, 12, 1), _paris(2026, 12, 20), _paris(2026, 12, 24, 23)):
        monkeypatch.setattr(ss, "paris_day", lambda now=None, _d=day: _d.date())
        before = [se.build_panel_embed(content, ss.happening(content, day)), se.build_advent_announcement(content.advent),
                  se.build_drop_announcement(content.drops[0], "Sucre d'orge")]
        status = ChristmasStatus(c, False, False, ss.kindness(1, 3), c.gift_for(ss.kindness(1, 3)), 10, {})
        before.append(se.build_christmas_embed(status))
        for embed in before:
            text = _texts(embed)
            assert "petite fille" not in text and "aid" not in text and "sage" not in text, text
            seen.append(text)
    monkeypatch.setattr(ss, "paris_day", lambda now=None: _paris(2026, 12, 26).date())
    after = [se.build_christmas_announcement(c, content.shops),
             se.build_panel_embed(content, ss.happening(content, _paris(2026, 12, 26)))]
    for tier, k in (("naughty", ss.kindness(1, 3)), ("angel", ss.kindness(3, 0)), ("unknown", ss.kindness(0, 0))):
        status = ChristmasStatus(c, True, False, k, c.gift_for(k), 10, {})
        after.append(se.build_christmas_embed(status, granted=status.lines))
        after.append(se.build_christmas_embed(ChristmasStatus(c, True, True, k, (), 10, {})))
    for embed in after:
        text = _texts(embed)
        assert "petite fille" not in text and "aid" not in text and "%" not in text, text
    tuto = Path("tuto.txt").read_text(encoding="utf-8")
    section = tuto[tuto.index("/evenement"):tuto.index("/evenement") + 2500]
    assert "petite fille" not in section.lower() and "% d'aide" not in tuto
