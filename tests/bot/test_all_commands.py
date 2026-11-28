"""Chaque commande slash du bot, et chaque bouton de sa réponse, sur une base
remplie du vrai contenu (audit du 28/11/2026).

Les cogs ne couvraient que 38 % de leur code : une commande pouvait planter
sans qu'aucun test le voie (seulement les joueurs). Ici, les 80 commandes
sont lancées comme par Discord — un joueur existant puis un nouveau venu —,
leurs réponses vérifiées (limites de Discord, une seule réponse primaire),
puis chaque bouton et chaque menu de leurs écrans cliqué par le vrai chemin
de discord.py. Aucune exception, aucune erreur ni avertissement au journal.
Harnais : `command_harness.py`.
"""

from __future__ import annotations

import asyncio
import logging
import os

os.environ.setdefault("ADMIN_SESSION_SECRET", "test-secret-for-pytest-only-32chars-min-aaaaa")

import discord
import pytest

from tests.bot import command_harness as h

#: Pas de clic sur leurs écrans : ils lancent (pour de vrai) le reset de tout.
NO_CLICK = {"admin lancer_saison", "admin reset_player"}


class _Journal(logging.Handler):
    def __init__(self):
        super().__init__(logging.WARNING)
        self.records: list[logging.LogRecord] = []

    def emit(self, record):
        if record.name.startswith(("app", "discord.ui")):
            self.records.append(record)


@pytest.fixture
def bot():
    from app.infrastructure.db import session as db_session

    old = h.install_database()
    journal = _Journal()
    logging.getLogger().addHandler(journal)
    loop = asyncio.new_event_loop()
    try:
        robot = h.make_bot()
        failed = loop.run_until_complete(h.load_cogs(robot))
        robot.journal = journal
        robot.loop_ = loop
        robot.load_failures = failed
        yield robot
    finally:
        logging.getLogger().removeHandler(journal)
        for task in asyncio.all_tasks(loop):
            task.cancel()
        loop.run_until_complete(asyncio.sleep(0))
        loop.close()
        db_session.SessionLocal.configure(bind=old)


def _commands(bot):
    return [c for c in bot.tree.walk_commands() if isinstance(c, discord.app_commands.Command)]


def _channel():
    from app.infrastructure.config.settings import settings

    return (settings.command_channel_ids or [1])[0]


def _journal_lines(bot):
    return [f"{r.levelname} {r.name}: {r.getMessage()[:200]}" for r in bot.journal.records]


def test_tous_les_cogs_se_chargent(bot):
    assert bot.load_failures == []
    assert len(_commands(bot)) >= 80


def test_chaque_commande_repond_et_chaque_bouton_marche(bot):
    channel, problems, clicked = _channel(), [], 0

    async def run():
        nonlocal clicked
        for command in _commands(bot):
            name = command.qualified_name
            try:
                inter, _ = await asyncio.wait_for(h.call_command(bot, command, 424242, channel, full=True), 60)
            except Exception as exc:
                problems.append(f"/{name} : {type(exc).__name__} {exc}")
                continue
            if not inter._sent.calls:
                problems.append(f"/{name} : aucune réponse")
            if name in NO_CLICK:
                continue
            for view in h.sent_views(inter):
                errors = []
                await h.click_everything(bot, view, 424242, channel, errors)
                clicked += sum(isinstance(i, (discord.ui.Button, discord.ui.Select)) for i in view.children)
                problems.extend(f"/{name} › {v} « {label} » : {type(e).__name__} {e}" for v, label, e in errors)

    bot.loop_.run_until_complete(run())
    assert problems == [], "\n".join(problems)
    assert _journal_lines(bot) == []
    assert clicked >= 50


def test_un_nouveau_venu_peut_tout_lancer(bot):
    """Un compte sans profil : chaque commande le crée ou refuse proprement."""
    channel, problems = _channel(), []

    async def run():
        for command in _commands(bot):
            try:
                inter, _ = await asyncio.wait_for(h.call_command(bot, command, 515151, channel), 60)
                if not inter._sent.calls:
                    problems.append(f"/{command.qualified_name} : aucune réponse")
            except Exception as exc:
                problems.append(f"/{command.qualified_name} : {type(exc).__name__} {exc}")

    bot.loop_.run_until_complete(run())
    assert problems == [], "\n".join(problems)
    assert _journal_lines(bot) == []


def test_les_cogs_se_chargent_deux_fois_dans_le_meme_processus(bot):
    """discord.py exécute le fichier d'une extension à chaque chargement : une
    commande `/admin` restée dans `admin_cog.py` se réinscrirait dans le groupe
    partagé (`admin_group`) et ferait échouer le second chargement (constaté
    pendant le découpage du 28/11/2026)."""
    second = h.make_bot()
    assert bot.loop_.run_until_complete(h.load_cogs(second)) == []
    names = {c.qualified_name for c in second.tree.walk_commands()}
    assert len([n for n in names if n.startswith("admin ")]) == 23
