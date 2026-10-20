"""Boucle des notifications de temps de recharge (case « Confort »).

Toutes les minutes : les temps de recharge échus depuis peu, pas encore
annoncés, déclenchent un message privé chez les joueurs qui ont la
fonctionnalité `notify_cooldowns`. Chaque échéance n'est annoncée qu'UNE fois
(colonne `notified_for`), même après un redémarrage du bot.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, UTC

from discord.ext import commands, tasks

from app.bot.notifications import COOLDOWN_LABELS, holders_of, send_dm
from app.infrastructure.db.repositories.cooldown_repository import CooldownRepository
from app.infrastructure.db.session import get_db_session

_logger = logging.getLogger("sakura.notifications")

#: On n'annonce pas une échéance plus vieille que ça (évite une rafale de MP
#: au premier démarrage, ou après une longue coupure du bot).
LOOKBACK = timedelta(minutes=30)


class NotificationCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.cooldown_loop.start()

    def cog_unload(self) -> None:
        self.cooldown_loop.cancel()

    @tasks.loop(minutes=1)
    async def cooldown_loop(self) -> None:
        try:
            now = datetime.now(UTC)
            to_send: list[tuple[int, str]] = []
            with get_db_session() as session:
                repo = CooldownRepository(session)
                due = repo.list_due_unnotified(now, now - LOOKBACK, set(COOLDOWN_LABELS))
                if not due:
                    return
                holders = holders_of(session, "notify_cooldowns")
                for cooldown_id, player_id, action_key, next_at in due:
                    # Marqué dans tous les cas : sans la fonctionnalité, on ne
                    # repasse pas sur cette échéance à chaque minute.
                    repo.mark_notified(cooldown_id, next_at)
                    if player_id in holders:
                        to_send.append((holders[player_id], COOLDOWN_LABELS[action_key]))
                session.commit()
            for discord_id, text in to_send:
                await send_dm(self.bot, discord_id, text)
        except Exception:  # noqa: BLE001 — la boucle ne doit jamais mourir
            _logger.exception("cooldown_loop failed")

    @cooldown_loop.before_loop
    async def _before(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(NotificationCog(bot))
