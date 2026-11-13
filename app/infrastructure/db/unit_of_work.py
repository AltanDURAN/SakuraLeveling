"""Écritures ATOMIQUES (roadmap N8, 26/10/2026).

Les dépôts valident eux-mêmes leurs écritures (`commit`) : pratique pour une
opération simple, dangereux pour une opération en plusieurs étapes — un achat
(or retiré, puis objet ajouté), un échange, un virement : un plantage entre
deux laissait un état à moitié fait (or perdu, objet dupliqué).

    with atomic(session):
        players.add_gold(acheteur, -prix)
        inventory.add_item(acheteur, objet, 1)

Dans un bloc `atomic`, les dépôts n'envoient que leurs écritures (`flush`) ;
tout est validé ENSEMBLE à la sortie, ou annulé si une exception s'échappe.
Les blocs s'imbriquent : seul le plus extérieur valide.
"""

from __future__ import annotations

import functools
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import text
from sqlalchemy.orm import Session

_DEPTH = "atomic_depth"


def lock_for_write(session: Session) -> None:
    """SQLite : prend le verrou d'écriture MAINTENANT, avant toute lecture
    (`BEGIN IMMEDIATE`).

    Sans ça, la transaction ne commence qu'à la PREMIÈRE ÉCRITURE : deux
    actions du même joueur lancées ensemble (deux clics, traités dans deux
    threads) lisaient chacune le même état — deux copies, un point à placer,
    une récompense à prendre — puis écrivaient l'une après l'autre. Reproduit
    le 13/11/2026 : fusion faite deux fois avec deux copies (47 courses sur
    100), récompense de la tour payée deux fois (36 sur 200). Avec le verrou,
    la seconde attend la fin de la première puis relit l'état à jour : sa
    vérification échoue comme il se doit.

    - Les écritures en attente partent d'abord (`flush`) : `expire_all` ne
      doit jamais en effacer une.
    - `expire_all` : ce que la session a lu AVANT le verrou est relu sous le
      verrou.
    - Sans effet hors SQLite. Si une transaction est déjà ouverte sur la
      connexion (une écriture a déjà pris le verrou), on ne fait que relire.
    """
    try:
        if session.get_bind().dialect.name != "sqlite":
            return
        session.flush()
        raw = session.connection().connection.dbapi_connection
        in_transaction = bool(getattr(raw, "in_transaction", True))
    except Exception:  # noqa: BLE001 — session sans base (tests) : pas de verrou
        return
    if not in_transaction:
        session.execute(text("BEGIN IMMEDIATE"))
    session.expire_all()


def locked_write(method):
    """Décorateur d'une méthode de dépôt qui LIT puis ÉCRIT une même valeur
    (solde d'or, quantité d'un objet) : le verrou d'écriture est pris avant
    la lecture, pour qu'une écriture concurrente ne soit jamais écrasée.
    Ne change rien à qui valide : la méthode garde son `commit` / `flush`."""
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        lock_for_write(self.session)
        return method(self, *args, **kwargs)
    return wrapper


@contextmanager
def atomic(session: Session) -> Iterator[Session]:
    depth = session.info.get(_DEPTH, 0)
    if depth == 0:
        lock_for_write(session)
    session.info[_DEPTH] = depth + 1
    try:
        yield session
    except BaseException:
        session.info[_DEPTH] = depth
        if depth == 0:
            session.rollback()
        raise
    session.info[_DEPTH] = depth
    if depth == 0:
        session.commit()


def in_atomic(session: Session) -> bool:
    return session.info.get(_DEPTH, 0) > 0


def commit(session: Session) -> None:
    """À la place de `session.commit()` dans les dépôts et services : dans un
    bloc `atomic`, simple `flush` (la validation se fait à la sortie)."""
    if in_atomic(session):
        session.flush()
    else:
        session.commit()


def _session_of(obj) -> Session:
    """La session d'un cas d'usage : `self.session`, sinon celle d'un dépôt."""
    session = getattr(obj, "session", None)
    if isinstance(session, Session):
        return session
    for value in vars(obj).values():
        if isinstance(getattr(value, "session", None), Session):
            return value.session
    raise RuntimeError(f"{type(obj).__name__} : aucune session trouvée pour @transactional")


def transactional(method):
    """Décorateur de méthode de cas d'usage : tout le corps est atomique."""
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        with atomic(_session_of(self)):
            return method(self, *args, **kwargs)
    return wrapper
