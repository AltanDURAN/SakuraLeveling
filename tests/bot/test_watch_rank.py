"""MP aux admins quand un joueur atteint le dernier palier prêt de la V1
(Rang C, Sanctuaire primordial — 25/11/2026, demande de l'auteur)."""

import asyncio
from types import SimpleNamespace

from app.bot.cogs import rank_trial_cog as rtc


def test_le_message_nomme_le_joueur_la_zone_et_la_suivante():
    text = rtc.watch_rank_message("Ruinflex", 46, 2)
    assert rtc.WATCH_RANK == "C"
    assert "**Ruinflex**" in text and "Rang C" in text and "Sanctuaire primordial" in text
    assert "Éclipse éternelle" in text and "niveau **46**" in text and "2 joueurs" in text


def _cog(monkeypatch, admins=(1, 2)):
    sent = []

    async def send_dm(bot, discord_id, content):
        sent.append(discord_id)
        return True

    import app.bot.notifications as notifications

    monkeypatch.setattr(notifications, "send_dm", send_dm)
    monkeypatch.setattr(rtc.settings.__class__, "admin_ids", property(lambda self: list(admins)))
    monkeypatch.setattr(rtc, "get_db_session", None)            # le comptage est remplacé
    cog = object.__new__(rtc.RankTrialCog)
    cog.bot = None
    return cog, sent


def test_seul_le_rang_surveille_et_un_vrai_joueur_previennent_les_admins(monkeypatch):
    cog, sent = _cog(monkeypatch)
    monkeypatch.setattr(asyncio, "to_thread", _fake_thread)
    asyncio.run(cog.warn_admins(SimpleNamespace(id=50, display_name="Tayud"), "D", 34))
    assert sent == []                                            # un autre rang : rien
    asyncio.run(cog.warn_admins(SimpleNamespace(id=1, display_name="Admin"), "C", 46))
    assert sent == []                                            # un compte admin : rien
    asyncio.run(cog.warn_admins(SimpleNamespace(id=50, display_name="Tayud"), "C", 46))
    assert sent == [1, 2]                                        # chaque admin


async def _fake_thread(func, *args, **kwargs):
    return 1
