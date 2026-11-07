"""File d'attente des vidéos de combat (audit du 06/11/2026).

Un rendu prend ~10 s et plusieurs centaines de Mo : mesuré, 3 vidéos en même
temps montaient à 3,3 Go sur un serveur de 1,8 Go. Elles passent donc UNE à la
fois. L'attente est bornée : si la file est trop longue, le combat de zone
saute sa vidéo et passe au récapitulatif (le joueur ne perd que l'animation) ;
un assaut de boss, lui, attend plus longtemps (un seul par jour, il se regarde).
"""

from __future__ import annotations

import asyncio
import contextlib
import weakref
from collections.abc import AsyncIterator

#: Attente maximale d'un combat de zone, en secondes.
ZONE_WAIT_S = 45.0
#: Attente maximale d'un assaut de world boss, en secondes.
BOSS_WAIT_S = 180.0

_slots: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()


def _slot() -> asyncio.Semaphore:
    """Un sémaphore par boucle asyncio (un seul en prod ; un par test)."""
    loop = asyncio.get_running_loop()
    slot = _slots.get(loop)
    if slot is None:
        slot = _slots[loop] = asyncio.Semaphore(1)
    return slot


@contextlib.asynccontextmanager
async def video_slot(timeout: float = ZONE_WAIT_S) -> AsyncIterator[bool]:
    """Réserve le rendu : `async with video_slot() as granted`. `granted` est
    faux si l'attente a dépassé `timeout` : il faut alors se passer de vidéo."""
    slot = _slot()
    try:
        await asyncio.wait_for(slot.acquire(), timeout)
    except asyncio.TimeoutError:
        yield False
        return
    try:
        yield True
    finally:
        slot.release()
