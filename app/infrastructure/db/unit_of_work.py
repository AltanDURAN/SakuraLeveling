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

from sqlalchemy.orm import Session

_DEPTH = "atomic_depth"


@contextmanager
def atomic(session: Session) -> Iterator[Session]:
    depth = session.info.get(_DEPTH, 0)
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
