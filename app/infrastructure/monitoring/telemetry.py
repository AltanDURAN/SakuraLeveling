"""Journal de surveillance (`game_events`) : une ligne par chose qui arrive.

    record(session, kinds.SHOP_BUY, player_id=pid, ref=item.code, qty=2, gold=-300)

L'écriture part avec la transaction du jeu (même session) : un achat annulé
n'est pas journalisé. Elle ne lève JAMAIS : la surveillance ne doit pas
casser une partie.

Les interactions Discord (commandes, boutons) passent par un TAMPON vidé
toutes les 30 s par le bot (`InteractionBuffer`) : une écriture SQLite à
chaque clic bloquerait la boucle du bot.
"""

from __future__ import annotations

import json
import logging
import threading
import weakref
from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import inspect, select, update
from sqlalchemy.orm import Session

from app.infrastructure.db.models.monitoring_model import GameEventModel
from app.infrastructure.db.models.player_model import PlayerModel

_logger = logging.getLogger(__name__)


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _event(kind: str, *, player_id=None, discord_id=None, zone=None, ref=None, gold=0, xp=0,
           qty=0, data=None, at: datetime | None = None) -> GameEventModel:
    if at is not None and at.tzinfo is not None:
        at = at.astimezone(UTC).replace(tzinfo=None)
    return GameEventModel(
        at=at or utcnow(), kind=kind, player_id=player_id, discord_id=discord_id,
        zone=str(zone)[:32] if zone else None, ref=str(ref)[:80] if ref else None,
        gold=int(gold or 0), xp=int(xp or 0), qty=int(qty or 0),
        data=json.dumps(data, ensure_ascii=False, separators=(",", ":")) if data else None,
    )


_READY: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()


def _ready(session: Session) -> bool:
    """La table existe-t-elle sur cette base ? (vérifié une fois par moteur).
    Une base sans la migration ne doit pas faire échouer l'action du joueur :
    l'INSERT raté emporterait toute sa transaction.

    ⚠️ On interroge la connexion DE LA SESSION : en ouvrir une autre (pool
    partagé d'une base en mémoire) annulait la transaction en cours."""
    try:
        engine = session.get_bind()
        engine = getattr(engine, "engine", engine)
        if engine not in _READY:
            _READY[engine] = inspect(session.connection()).has_table(GameEventModel.__tablename__)
            if not _READY[engine]:
                _logger.warning("Table %s absente : journal de surveillance désactivé.",
                                GameEventModel.__tablename__)
        return _READY[engine]
    except Exception:  # noqa: BLE001
        return False


def record(session: Session, kind: str, **fields) -> None:
    """Ajoute un événement à la transaction en cours (jamais d'exception)."""
    try:
        if not _ready(session):
            return
        session.add(_event(kind, **fields))
    except Exception:  # noqa: BLE001 — la surveillance ne casse jamais le jeu
        _logger.warning("Journal de surveillance : %s non enregistré", kind, exc_info=True)


def record_now(session_factory: Callable, kind: str, **fields) -> None:
    """Dans sa propre transaction (là où le jeu n'a pas de session ouverte)."""
    try:
        with session_factory() as session:
            if not _ready(session):
                return
            session.add(_event(kind, **fields))
            session.commit()
    except Exception:  # noqa: BLE001
        _logger.warning("Journal de surveillance : %s non enregistré", kind, exc_info=True)


def count(session: Session, kind: str, *, zone=None, amount: int = 1, at: datetime | None = None) -> None:
    """Compteur par HEURE et par zone : UNE ligne (kind, zone, heure) dont `qty`
    monte, au lieu d'une ligne par occurrence. Pour ce qui arrive des milliers
    de fois et dont seul le nombre sert — les monstres repartis sans combattant
    faisaient 98 % du journal (19 585 lignes sur 19 990 en onze jours, mesuré
    le 12/11/2026). Ne valide pas la transaction ; lève en cas d'échec."""
    if at is not None and at.tzinfo is not None:
        at = at.astimezone(UTC).replace(tzinfo=None)
    hour = (at or utcnow()).replace(minute=0, second=0, microsecond=0)
    zone = str(zone)[:32] if zone else None
    same_zone = GameEventModel.zone.is_(None) if zone is None else GameEventModel.zone == zone
    done = session.execute(
        update(GameEventModel)
        .where(GameEventModel.kind == kind, GameEventModel.at == hour, same_zone)
        .values(qty=GameEventModel.qty + int(amount))
        .execution_options(synchronize_session=False)
    ).rowcount
    if not done:
        session.add(_event(kind, zone=zone, qty=int(amount), at=hour))


def count_now(session_factory: Callable, kind: str, *, zone=None, amount: int = 1) -> None:
    """`count` dans sa propre transaction (jamais d'exception)."""
    try:
        with session_factory() as session:
            if not _ready(session):
                return
            count(session, kind, zone=zone, amount=amount)
            session.commit()
    except Exception:  # noqa: BLE001
        _logger.warning("Journal de surveillance : compteur %s non enregistré", kind, exc_info=True)


class InteractionBuffer:
    """Tampon des interactions Discord, vidé par lots."""

    MAX_PENDING = 5000

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._pending: list[tuple[datetime, int, str, str]] = []

    def push(self, discord_id: int, ref: str, kind: str = "interaction", at: datetime | None = None) -> None:
        with self._lock:
            if len(self._pending) < self.MAX_PENDING:
                self._pending.append((at or utcnow(), discord_id, kind, ref[:80]))

    def __len__(self) -> int:
        return len(self._pending)

    def clear(self) -> int:
        """Oublie ce qui attend (reset de saison : rien d'avant ne doit
        atterrir dans le nouveau journal)."""
        with self._lock:
            dropped, self._pending = len(self._pending), []
        return dropped

    def flush(self, session: Session) -> int:
        """Écrit le tampon (un seul commit) et renvoie le nombre d'événements."""
        with self._lock:
            batch, self._pending = self._pending, []
        if not batch:
            return 0
        try:
            if not _ready(session):
                return 0
            ids = {d for _, d, _, _ in batch}
            players = dict(session.execute(
                select(PlayerModel.discord_id, PlayerModel.id).where(PlayerModel.discord_id.in_(ids))).all())
            session.add_all(GameEventModel(at=at, kind=kind, discord_id=d, player_id=players.get(d), ref=ref)
                            for at, d, kind, ref in batch)
            session.commit()
        except Exception:  # noqa: BLE001
            session.rollback()
            _logger.warning("Journal de surveillance : %d interactions perdues", len(batch), exc_info=True)
            return 0
        return len(batch)


#: Tampon unique du processus du bot.
interactions = InteractionBuffer()
