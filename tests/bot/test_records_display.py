"""Salon des records (07/11/2026) : tableau, nouvelles de la nuit (qui est
mentionné), `/records`, et publication dans le salon."""

import asyncio
from datetime import date, datetime
from types import SimpleNamespace

import discord

from app.application.use_cases.records import NightReport, PersonalView
from app.bot.cogs import records_cog
from app.bot.embeds import records_embeds as re_
from app.domain.services import records_service as rs

FAMILIES = [("slime", "slimes"), ("gobelin", "gobelins"), ("mort-vivant", "morts-vivants"), ("demoniaque", "démons"),
            ("primordial", "bêtes primordiales"), ("nocturne", "créatures nocturnes"), ("draconique", "dragons")]
RECORDS = rs.all_records(FAMILIES)
NAMES = {1: (111, "Alice"), 2: (222, "Bob"), 3: (333, "Chloé")}
AT = datetime(2026, 11, 7, 12, 0)


def _full_board():
    held = {r.code: rs.Entry(1 + i % 3, 1_234_567 + i, AT, "Gobelin Runique et Archidémon") for i, r in enumerate(RECORDS)}
    return held, rs.ranking(held)


def test_le_tableau_tient_dans_un_message():
    held, standings = _full_board()
    embed = re_.build_board_embed(RECORDS, held, standings, NAMES, date(2026, 11, 8))
    assert len(embed) <= 6000 and all(len(f.value) <= 1024 for f in embed.fields)
    assert "<@111>" in embed.fields[0].value and "8 novembre 2026" in embed.footer.text
    assert "Légende des records" in embed.description and "+5 % d'or" in embed.description
    tower = next(f.value for f in embed.fields if f.name.startswith("🗼"))
    assert f"**étage {held['tour'].value}**" in tower                 # un étage, pas des « dégâts »


def test_les_nouvelles_de_la_nuit_mentionnent_les_nouveaux_detenteurs():
    coup, soin = rs.EXPLOITS[0], rs.EXPLOITS[2]
    moved = [rs.Change(coup, rs.Entry(2, 650, AT), rs.Entry(1, 500, AT)),
             rs.Change(soin, rs.Entry(3, 400, AT), rs.Entry(3, 300, AT))]
    news, ping = re_.build_news(moved, {"records_1": 2}, [rs.Standing(2, 3, AT)], NAMES)
    assert "<@222> bat <@111>" in news.description and "améliore son record" in news.description
    assert ping == [2, 3]                                            # pas l'ancien détenteur
    assert re_.build_news([], {}, [], NAMES) == (None, [])


def test_records_dit_ou_en_est_le_joueur():
    coup, soin, tour, boss = rs.EXPLOITS[0], rs.EXPLOITS[2], rs.TOWER, rs.BOSS
    view = PersonalView(records=[coup, soin, tour, boss],
                        held={"coup": rs.Entry(2, 650, AT), "soin": rs.Entry(1, 300, AT), "tour": rs.Entry(2, 12, AT)},
                        mine={"coup": rs.Entry(1, 600, AT), "soin": rs.Entry(1, 300, AT), "tour": rs.Entry(1, 14, AT),
                              "boss": rs.Entry(1, 9000, AT)},
                        names=NAMES)
    text = " ".join(f.value for f in re_.build_personal_embed(view, 1).fields)
    assert "il te manque **51**" in text                             # strictement mieux : 650 - 600 + 1
    assert "👑 **c'est toi**" in text and "🔥 toi **étage 14** : mieux que le record !" in text
    assert "à toi cette nuit" in text                                # personne ne détient le record du boss


class Channel:
    def __init__(self):
        self.sent, self.pinned = [], []

    async def send(self, content=None, embed=None, allowed_mentions=None):
        message = SimpleNamespace(id=len(self.sent) + 10, content=content, embed=embed,
                                  allowed_mentions=allowed_mentions, pinned=False)
        self.sent.append(message)
        return message

    async def fetch_message(self, message_id):
        raise discord.NotFound(SimpleNamespace(status=404, reason="absent"), "Unknown Message")


def test_la_nuit_est_publiee_dans_le_salon(monkeypatch):
    channel = Channel()
    cog = object.__new__(records_cog.RecordsCog)
    cog.bot = SimpleNamespace(get_channel=lambda _: channel, user=SimpleNamespace(id=1))
    pinned, saved = [], []

    async def pin(channel_, message, bot_id):
        pinned.append(message.id)

    monkeypatch.setattr(records_cog, "pin_message", pin)
    monkeypatch.setattr(records_cog.RecordsCog, "_save_message", staticmethod(saved.append))
    monkeypatch.setattr(records_cog.settings, "records_channel_id", 5)
    held, standings = _full_board()
    report = NightReport(day=date(2026, 11, 8), records=RECORDS, held=held,
                         changes=[rs.Change(RECORDS[0], held["coup"], None)], standings=standings,
                         titles=rs.title_awards(standings), new_titles={"records_1": 1}, names=NAMES, first=True,
                         message_id=999)
    asyncio.run(cog.publish(report))
    board, news = channel.sent
    assert pinned == [board.id] and saved == [board.id]              # le tableau perdu est reposté et épinglé
    assert news.embed.title == "🏆 Les premiers records" and news.content == "<@111>"
    assert [u.id for u in news.allowed_mentions.users] == [111]
