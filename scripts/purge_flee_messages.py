"""Retire les anciens messages de fuite des salons de zone.

Jusqu'au 07/11/2026, un monstre parti sans combattant laissait un message
(« 🌫️ Le X s'est échappé ») : près de 28 000 par zone, qui noyaient les vrais
combats. Le bot ne les pose plus ; ce script retire ceux qui restent, et rien
d'autre (`is_flee_message`).

    .venv/bin/python -m scripts.purge_flee_messages                       # aperçu, ne supprime rien
    .venv/bin/python -m scripts.purge_flee_messages --confirm --limit 5   # essai : 5 par zone
    .venv/bin/python -m scripts.purge_flee_messages --confirm             # tout

Il passe par l'API REST avec le jeton du bot : pas de seconde connexion, le bot
continue de tourner. Les zones avancent ensemble. Les messages de moins de
14 jours partent par lots de 100 ; Discord n'accepte les plus vieux qu'un par
un (`--pause` entre deux). Coupé en route, il suffit de le relancer : il ne voit
plus que ce qui reste.
"""

from __future__ import annotations

import argparse
import asyncio
import signal
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import aiohttp

API = "https://discord.com/api/v10"
FLEE_START = "🌫"
FLEE_END = "s'est échappé"
FLEE_TEXT = "Personne ne s'est présenté pour combattre."
PAGE_SIZE = 100
BULK_MAX_AGE = timedelta(days=13, hours=20)     # Discord refuse au-delà de 14 jours
BULK_MIN = 2                                    # et en dessous de 2 messages
MAX_FAILURES = 8
REPORT_EVERY = 1000


def is_flee_message(message: dict, bot_id: str) -> bool:
    """Un message de fuite et rien d'autre : posé par le bot, un seul embed au
    titre et au texte de la fuite, sans texte à côté, sans bouton, sans pièce
    jointe. Un message épinglé n'est jamais touché."""
    if message.get("author", {}).get("id") != bot_id:
        return False
    if any(message.get(key) for key in ("pinned", "content", "components", "attachments")):
        return False
    embeds = message.get("embeds") or []
    if len(embeds) != 1:
        return False
    title = embeds[0].get("title") or ""
    text = embeds[0].get("description") or ""
    return title.startswith(FLEE_START) and title.endswith(FLEE_END) and text.startswith(FLEE_TEXT)


def split_by_age(messages: list[dict], now: datetime) -> tuple[list[str], list[str]]:
    """(par lot, un par un) : les identifiants, selon ce que Discord accepte."""
    recent, old = [], []
    for message in messages:
        young = now - datetime.fromisoformat(message["timestamp"]) < BULK_MAX_AGE
        (recent if young else old).append(message["id"])
    return (recent, old) if len(recent) >= BULK_MIN else ([], recent + old)


class DiscordApi:
    """Appels REST : attend ce que Discord demande, réessaie les pannes."""

    def __init__(self, session: aiohttp.ClientSession, token: str):
        self.session = session
        self.headers = {"Authorization": f"Bot {token}"}
        self.throttled = 0

    async def call(self, method: str, path: str, **kwargs) -> tuple[int, Any]:
        failures = 0
        while failures < MAX_FAILURES:
            try:
                async with self.session.request(method, API + path, headers=self.headers, **kwargs) as response:
                    if response.status == 429:
                        self.throttled += 1
                        await asyncio.sleep(float(response.headers.get("Retry-After", 5)) + 0.25)
                        continue
                    if response.status < 500:
                        return response.status, await response.json() if response.status == 200 else None
            except (aiohttp.ClientError, TimeoutError):
                pass
            failures += 1
            await asyncio.sleep(5 * failures)
        raise RuntimeError(f"Discord ne répond plus ({method} {path})")

    async def history(self, channel_id: int, before: str | None) -> list[dict]:
        query = f"?limit={PAGE_SIZE}" + (f"&before={before}" if before else "")
        status, page = await self.call("GET", f"/channels/{channel_id}/messages{query}")
        if status != 200:
            raise RuntimeError(f"historique du salon {channel_id} refusé ({status})")
        return page

    async def bulk_delete(self, channel_id: int, ids: list[str]) -> int:
        status, _ = await self.call("POST", f"/channels/{channel_id}/messages/bulk-delete", json={"messages": ids})
        return status

    async def delete(self, channel_id: int, message_id: str) -> int:
        status, _ = await self.call("DELETE", f"/channels/{channel_id}/messages/{message_id}")
        return status


@dataclass
class ZoneReport:
    name: str
    seen: int = 0
    found: int = 0
    removed: int = 0
    error: str = ""

    def line(self) -> str:
        text = f"{self.name} : {self.seen} messages lus, {self.found} fuites, {self.removed} retirées"
        return f"{text} — {self.error}" if self.error else text


async def _remove(api, channel_id: int, messages: list[dict], report: ZoneReport, pause: float,
                  stop: asyncio.Event) -> None:
    recent, old = split_by_age(messages, datetime.now(UTC))
    if recent:
        if await api.bulk_delete(channel_id, recent) == 204:
            report.removed += len(recent)
        else:
            old = recent + old          # lot refusé : un par un
    for message_id in old:
        if stop.is_set():
            return
        status = await api.delete(channel_id, message_id)
        if status == 403:
            report.error = "suppression refusée (403)"
            return
        report.removed += status in (204, 404)      # 404 : déjà parti
        await asyncio.sleep(pause)


async def purge_zone(api, name: str, channel_id: int, bot_id: str, *, confirm: bool, pause: float = 1.0,
                     limit: int = 0, stop: asyncio.Event | None = None) -> ZoneReport:
    """Parcourt le salon du plus récent au plus ancien : ce qui peut partir par
    lots passe d'abord, avant d'avoir 14 jours."""
    stop = stop or asyncio.Event()
    report = ZoneReport(name)
    before = None
    while not stop.is_set() and not report.error:
        page = await api.history(channel_id, before)
        if not page:
            break
        before = page[-1]["id"]
        report.seen += len(page)
        targets = [m for m in page if is_flee_message(m, bot_id)]
        report.found += len(targets)
        if confirm:
            await _remove(api, channel_id, targets[:limit - report.removed] if limit else targets, report,
                          pause, stop)
            if limit and report.removed >= limit:
                break
        if report.seen % REPORT_EVERY == 0:
            print(f"{datetime.now():%H:%M:%S} {report.line()} ({api.throttled} attentes imposées)", flush=True)
    return report


async def run(args: argparse.Namespace) -> None:
    from app.infrastructure.config.settings import settings
    from app.infrastructure.encounters.farm_zone_loader import list_zones

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(signum, stop.set)

    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
        api = DiscordApi(session, settings.discord_token)
        _, me = await api.call("GET", "/users/@me")
        zones = [z for z in list_zones() if z.get("channel_id")]
        print(("Suppression" if args.confirm else "Aperçu, rien n'est supprimé") + f" : {len(zones)} zones", flush=True)
        reports = await asyncio.gather(*(
            purge_zone(api, z["name"], int(z["channel_id"]), me["id"], confirm=args.confirm, pause=args.pause,
                       limit=args.limit, stop=stop)
            for z in zones))
    for report in reports:
        print(report.line(), flush=True)
    print(f"Total : {sum(r.found for r in reports)} fuites vues, {sum(r.removed for r in reports)} retirées, "
          f"{api.throttled} attentes imposées par Discord", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Retire les anciens messages de fuite des salons de zone.")
    parser.add_argument("--confirm", action="store_true", help="supprime vraiment (sinon, aperçu)")
    parser.add_argument("--limit", type=int, default=0, help="au plus N messages par zone (0 = tout)")
    parser.add_argument("--pause", type=float, default=1.0, help="secondes entre deux suppressions à l'unité")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
