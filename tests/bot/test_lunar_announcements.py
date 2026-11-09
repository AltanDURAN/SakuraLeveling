"""Annonces lunaires : rappel, lever et fin dans le salon GÉNÉRAL seulement
(09/11/2026, demande de l'auteur : plus dans les salons de zone)."""

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from app.bot.cogs import lunar_cog
from app.domain.services import lunar_service
from app.infrastructure.config.settings import settings

GENERAL = 4242
START = datetime(2026, 11, 24, 16, 1, tzinfo=UTC)
EVENT = lunar_service.LunarEvent("pleine_lune", START, START + timedelta(hours=15))


class _Clock(datetime):
    current = START

    @classmethod
    def now(cls, tz=None):
        return cls.current


def test_rappel_lever_et_fin_ne_partent_que_dans_le_general(monkeypatch):
    asked, sent = [], []

    class Channel:
        def __init__(self, channel_id):
            self.id = channel_id

        async def send(self, embed=None):
            sent.append((self.id, embed.title))

    def get_channel(channel_id):
        asked.append(channel_id)
        return Channel(channel_id)

    cog = lunar_cog.LunarCog.__new__(lunar_cog.LunarCog)       # sans lancer la boucle
    cog.bot = SimpleNamespace(get_channel=get_channel)
    cog._announced, cog._current, cog._first_tick = set(), None, False
    monkeypatch.setattr(settings, "rank_announce_channel_id", GENERAL)
    monkeypatch.setattr(lunar_cog, "datetime", _Clock)
    sky = {"active": None, "coming": []}
    monkeypatch.setattr(lunar_cog.lunar_service, "active_event", lambda now, rules: sky["active"])
    monkeypatch.setattr(lunar_cog.lunar_service, "upcoming", lambda now, rules, days: sky["coming"])

    def tick(now, active, coming):
        _Clock.current, sky["active"], sky["coming"] = now, active, coming
        asyncio.run(lunar_cog.LunarCog.sky_loop.coro(cog))

    tick(START - timedelta(hours=2), None, [EVENT])             # rappel
    tick(START + timedelta(minutes=1), EVENT, [])               # lever
    tick(EVENT.end + timedelta(minutes=1), None, [])            # fin

    assert [title for _, title in sent] == ["🌕 Pleine lune ce soir", "🌕 Pleine lune !", "🌕 Fin : Pleine lune"]
    assert set(asked) == {GENERAL} and {channel for channel, _ in sent} == {GENERAL}
