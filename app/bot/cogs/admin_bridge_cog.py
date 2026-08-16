"""Pont admin WEB → bot.

La webapp d'administration tourne dans un PROCESSUS SÉPARÉ : elle sait écrire
en base (or, XP, items, titres…) mais ne peut pas parler à Discord. Pour les
actions qui exigent le bot — faire spawner un monstre, un boss, un événement,
couper un combat en cours — l'admin dépose une commande dans `admin_commands`
et ce cog la ramasse toutes les 5 secondes, l'exécute, puis écrit le résultat
(que la webapp réaffiche).

Chaque action délègue à l'API publique du cog concerné (`trigger_immediate_spawn`,
`force_end_encounter`, `admin_spawn_boss`, `spawn_event`…) : aucune logique
métier n'est dupliquée ici, c'est un simple aiguilleur.
"""

from __future__ import annotations

import json
import logging

from discord.ext import commands, tasks

from app.infrastructure.db.repositories.admin_command_repository import (
    KNOWN_ACTIONS,
    AdminCommandRepository,
)
from app.infrastructure.db.session import get_db_session

_logger = logging.getLogger(__name__)


class AdminBridgeCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.poll_loop.start()

    def cog_unload(self) -> None:
        self.poll_loop.cancel()

    @tasks.loop(seconds=5)
    async def poll_loop(self) -> None:
        try:
            with get_db_session() as session:
                pending = [
                    (c.id, c.action, c.payload_json)
                    for c in AdminCommandRepository(session).list_pending()
                ]
            for command_id, action, payload_json in pending:
                try:
                    payload = json.loads(payload_json or "{}")
                except ValueError:
                    payload = {}
                ok, message = await self._execute(action, payload)
                with get_db_session() as session:
                    AdminCommandRepository(session).mark(
                        command_id, "done" if ok else "failed", message
                    )
                    session.commit()
                _logger.info(
                    "commande admin #%s %s → %s (%s)",
                    command_id, action, "done" if ok else "failed", message,
                )
        except Exception:  # noqa: BLE001
            _logger.exception("admin bridge poll_loop failed")

    @poll_loop.before_loop
    async def _before_poll(self) -> None:
        await self.bot.wait_until_ready()

    # ------------------------------------------------------------------
    async def _execute(self, action: str, payload: dict) -> tuple[bool, str]:
        if action not in KNOWN_ACTIONS:
            return False, f"Action inconnue : {action}"

        if action in ("spawn_encounter", "stop_encounter", "resolve_encounter"):
            cog = self.bot.get_cog("EncounterCog")
            if cog is None:
                return False, "EncounterCog non chargé."
            if action == "spawn_encounter":
                return cog.trigger_immediate_spawn(
                    mob_code=payload.get("mob_code") or None,
                    element=payload.get("element") or None,
                    channel_id=payload.get("channel_id") or None,
                )
            if action == "stop_encounter":
                return cog.force_end_encounter()
            return cog.request_early_resolve()

        if action in ("spawn_boss", "stop_boss"):
            cog = self.bot.get_cog("WorldBossCog")
            if cog is None:
                return False, "WorldBossCog non chargé."
            if action == "spawn_boss":
                return await cog.admin_spawn_boss(str(payload.get("boss_code", "")))
            return await cog.admin_stop_boss()

        if action == "spawn_event":
            cog = self.bot.get_cog("EventCog")
            if cog is None:
                return False, "EventCog non chargé."
            event_type = str(payload.get("event_type", ""))
            message = await cog.spawn_event(event_type)
            if message is None:
                return False, (
                    f"Impossible de faire spawner « {event_type} » "
                    "(type inconnu ou salon introuvable)."
                )
            return True, f"Événement « {event_type} » lancé."

        return False, f"Action non gérée : {action}"


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AdminBridgeCog(bot))
