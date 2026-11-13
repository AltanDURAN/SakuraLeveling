"""Guides épinglés des salons du world boss et de la tour (07/11/2026) : textes
tirés des vrais réglages, postés une fois, épinglés, réécrits s'ils changent."""

import asyncio
from types import SimpleNamespace

import discord

from app.bot.cogs import channel_guides_cog as cog
from app.bot.embeds import channel_guide_embeds as guides
from app.domain.services.pacing_service import RaidPacing
from app.domain.services.tower_service import DAILY_GOLD_PER_FLOOR, TOWER_FLOORS

BOT = 1


def _fits_discord(embed: discord.Embed) -> None:
    assert len(embed.fields) <= 25 and len(embed.description or "") <= 4096
    assert all(len(f.value) <= 1024 and len(f.name) <= 256 for f in embed.fields)
    assert len(embed) <= 6000


def _text(embed: discord.Embed) -> str:
    return " ".join([embed.title or "", embed.description or ""] + [f"{f.name} {f.value}" for f in embed.fields])


def test_le_guide_du_raid_suit_les_horaires_regles_sur_le_site():
    raid = RaidPacing(spawn_weekday=2, spawn_hour=18, fight_hour=20, fight_minute=30, registration_close_minutes=15)
    embed = guides.build_world_boss_guide(raid, first_raid_level=15, active_days=14)
    text = _text(embed)
    assert "mercredi à 18h" in text and "**20h30**" in text and "**20h15**" in text
    assert "le **mardi**" in text                                       # dernier assaut : la veille de l'arrivée
    assert "niveau **15**" in text and "+5 %" in text and "+50 %" in text
    _fits_discord(embed)
    assert embed.footer.text == guides.GUIDE_FOOTER


def test_le_premier_raid_attend_le_plus_petit_boss_moins_la_marge():
    assert guides.first_raid_level([60, 20, 40]) == 15
    assert guides.first_raid_level([]) == 1


def test_le_guide_de_la_tour_reprend_les_regles_du_jeu():
    embed = guides.build_tower_guide()
    text = _text(embed)
    assert f"{TOWER_FLOORS} étages" in text and f"{DAILY_GOLD_PER_FLOOR} or par étage" in text
    assert "sans potion ni élixir" in text and "victoire garde ton ticket" in text
    _fits_discord(embed)


class Message:
    def __init__(self, message_id, *, author=BOT, embed=None, pinned=False, type=discord.MessageType.default):
        self.id, self.author, self.pinned, self.type = message_id, SimpleNamespace(id=author), pinned, type
        self.embeds = [embed] if embed is not None else []
        self.edits, self.deleted = [], False

    async def pin(self, reason=None):
        self.pinned = True
        self.channel.messages.append(Message(99, type=discord.MessageType.pins_add))
        self.channel.messages[-1].channel = self.channel

    async def edit(self, **kwargs):
        self.edits.append(kwargs)
        self.embeds = [kwargs["embed"]]

    async def delete(self):
        self.deleted = True
        self.channel.messages.remove(self)


class Channel:
    id = 5

    def __init__(self, *messages):
        self.messages = list(messages)
        for message in self.messages:
            message.channel = self

    def pins(self, limit=50):
        async def gen():
            for message in [m for m in self.messages if m.pinned][::-1]:
                yield message
        return gen()

    def history(self, limit=100, oldest_first=False):
        async def gen():
            ordered = self.messages if oldest_first else self.messages[::-1]
            for message in ordered[:limit]:
                yield message
        return gen()

    async def send(self, embed=None, file=None):
        message = Message(len(self.messages) + 1, embed=embed)
        message.channel = self
        self.messages.append(message)
        return message


def _guide(embed=None):
    return cog.Guide(5, embed or guides.build_tower_guide(), guides.TOWER_BANNER, guides.TOWER_FILE)


def _banner(*args):
    return b"png"


def test_le_guide_est_poste_epingle_et_la_notice_retiree():
    channel = Channel()
    assert asyncio.run(cog.post_or_update_guide(channel, BOT, _guide(), banner=_banner)) == "posté"
    assert len(channel.messages) == 1                                   # la notice d'épinglage est partie
    guide = channel.messages[0]
    assert guide.pinned and guide.embeds[0].footer.text == guides.GUIDE_FOOTER


def test_un_guide_a_jour_n_est_pas_retouche_et_un_guide_change_est_reecrit():
    old = guides.build_tower_guide()
    current = Message(1, embed=old, pinned=True)
    channel = Channel(Message(0, author=2), current)
    assert asyncio.run(cog.post_or_update_guide(channel, BOT, _guide(), banner=_banner)) == "inchangé"
    assert not current.edits

    changed = guides.build_tower_guide()
    changed.description = "Nouvelle règle."
    assert asyncio.run(cog.post_or_update_guide(channel, BOT, _guide(changed), banner=_banner)) == "mis à jour"
    assert current.edits[-1]["embed"].description == "Nouvelle règle."
    assert len(channel.messages) == 2                                   # pas de second guide


def test_un_guide_desepingle_est_retrouve_en_tete_et_reepingle():
    current = Message(1, embed=guides.build_tower_guide(), pinned=False)
    channel = Channel(current, Message(2, author=2))
    assert asyncio.run(cog.post_or_update_guide(channel, BOT, _guide(), banner=_banner)) == "inchangé"
    assert current.pinned and len(channel.messages) == 2


def test_une_panne_sur_un_guide_n_arrete_pas_la_boucle(monkeypatch):
    """Une exception non rattrapée arrête une boucle `tasks.loop` jusqu'au
    redémarrage : une panne de Discord sur un salon ne doit ni tuer la boucle
    ni priver les autres salons de leur guide."""
    seen = []

    async def flaky(channel, bot_id, guide):
        seen.append(guide.channel_id)
        if guide.channel_id == 1:
            raise RuntimeError("Discord 503")
        return "posté"

    class Bot:
        user = type("U", (), {"id": BOT})()

        def get_channel(self, channel_id):
            return Channel()

    two = [cog.Guide(1, guides.build_tower_guide(), guides.TOWER_BANNER, guides.TOWER_FILE),
           cog.Guide(2, guides.build_tower_guide(), guides.TOWER_BANNER, guides.TOWER_FILE)]
    monkeypatch.setattr(cog, "current_guides", lambda: two)
    monkeypatch.setattr(cog, "post_or_update_guide", flaky)
    holder = type("C", (), {"bot": Bot()})()
    asyncio.run(cog.ChannelGuidesCog.refresh_loop.coro(holder))      # ne lève pas
    assert seen == [1, 2]
