"""File d'attente des vidéos de combat (audit du 06/11/2026, réglée le
28/11/2026 d'après des mesures sur le VPS).

Un rendu prend du temps et plusieurs centaines de Mo. Mesuré sur le VPS
(2 processeurs, 1,8 Go dont ~950 Mo disponibles bot en marche, la plus longue
vidéo de zone — meute de 3, 76 actions —, `scripts/measure_video_load.py`) :

| en même temps | durée totale | mémoire | disponible au plus bas |
|---|---|---|---|
| 1 | 17 s | +203 Mo | 694 Mo |
| 2 | 20 s (34 s l'une après l'autre) | +398 Mo | 496 Mo |
| 3 | 32 s | +587 Mo | 317 Mo |

Donc DEUX vidéos à la fois (×1,7 de débit), mais la seconde place ne s'ouvre
que s'il reste `SECOND_SLOT_MIN_MB` de mémoire disponible au moment de la
prendre : un serveur chargé (autres sites, montée en charge) retombe tout seul
à une vidéo à la fois. Trois, c'était frôler l'alerte de mémoire basse.

L'attente est bornée : si la file est trop longue, le combat de zone saute sa
vidéo et passe au récapitulatif (le joueur ne perd que l'animation) ; un
assaut de boss, lui, attend plus longtemps (un seul par jour, il se regarde).
"""

from __future__ import annotations

import asyncio
import contextlib
import time
import weakref
from collections.abc import AsyncIterator

#: Attente maximale d'un combat de zone, en secondes.
ZONE_WAIT_S = 45.0
#: Attente maximale d'un assaut de world boss, en secondes.
BOSS_WAIT_S = 180.0
#: Vidéos rendues en même temps, au plus.
MAX_SLOTS = 2
#: Mémoire disponible (Mo) qu'il faut pour ouvrir une place de plus qu'une :
#: une vidéo de plus coûte ~200 Mo et il doit en rester au moins ~500.
SECOND_SLOT_MIN_MB = 700


class _Queue:
    def __init__(self) -> None:
        self.active = 0
        self.changed = asyncio.Condition()


_queues: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()


def _queue() -> _Queue:
    """Une file par boucle asyncio (une seule en prod ; une par test)."""
    loop = asyncio.get_running_loop()
    queue = _queues.get(loop)
    if queue is None:
        queue = _queues[loop] = _Queue()
    return queue


def _available_mb() -> float | None:
    """Mémoire disponible en Mo ; None si on ne sait pas (hors Linux)."""
    try:
        from app.application.monitoring.alerting import _meminfo
        info = _meminfo()
        return info[0] if info else None
    except Exception:  # noqa: BLE001
        return None


def _can_start(active: int) -> bool:
    if active == 0:
        return True
    if active >= MAX_SLOTS:
        return False
    available = _available_mb()
    return available is not None and available >= SECOND_SLOT_MIN_MB


@contextlib.asynccontextmanager
async def video_slot(timeout: float = ZONE_WAIT_S) -> AsyncIterator[bool]:
    """Réserve le rendu : `async with video_slot() as granted`. `granted` est
    faux si l'attente a dépassé `timeout` : il faut alors se passer de vidéo."""
    queue = _queue()
    deadline = time.monotonic() + timeout
    async with queue.changed:
        while not _can_start(queue.active):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                # Réveillé à la fin d'une vidéo ; sinon on revérifie la
                # mémoire toutes les secondes (elle se libère aussi ailleurs).
                await asyncio.wait_for(queue.changed.wait(), min(remaining, 1.0))
            except asyncio.TimeoutError:
                pass
        granted = _can_start(queue.active)
        if granted:
            queue.active += 1
    if not granted:
        yield False
        return
    try:
        yield True
    finally:
        _note_memory()
        async with queue.changed:
            queue.active -= 1
            queue.changed.notify_all()


def _note_memory() -> None:
    """Relevé de mémoire à la fin d'une vidéo, le moment le plus gourmand
    (alerte « Mémoire du serveur basse »)."""
    try:
        from app.application.monitoring.alerting import note_memory
        note_memory()
    except Exception:  # noqa: BLE001 — un relevé ne fait jamais échouer un combat
        pass
