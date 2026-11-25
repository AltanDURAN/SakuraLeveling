"""Porte d'entrée du serveur (25/11/2026, demande de l'auteur).

Avant le lancement d'une saison, on ne laisse pas entrer de nouveaux joueurs
(pas d'avant-première) :
  • « ouverte »  : le parcours normal ;
  • « testeurs » : seuls ceux qui ont DÉJÀ accepté le règlement jouent ; un
    nouveau venu ne peut plus l'accepter ;
  • « fermee »   : plus personne (admins exceptés) ; les rôles du parcours
    sont retirés, chacun attend à l'entrée l'ouverture officielle.
Le lancement de la saison (`reset_season`) vide la table : la porte rouvre.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.infrastructure.db.models.entry_gate_model import EntryGateModel
from app.infrastructure.db.unit_of_work import atomic

OPEN, TESTERS, CLOSED = "ouverte", "testeurs", "fermee"
MODES = (OPEN, TESTERS, CLOSED)


@dataclass(frozen=True)
class Gate:
    mode: str = OPEN
    #: Ouverture annoncée (UTC, avec fuseau), ou None.
    opens_at: datetime | None = None

    @property
    def is_open(self) -> bool:
        return self.mode == OPEN

    def lets_in(self, *, accepted: bool) -> bool:
        """Un membre peut-il ACCEPTER le règlement (entrer) ?"""
        return self.mode == OPEN or (self.mode == TESTERS and accepted)


def read(session: Session) -> Gate:
    row = session.get(EntryGateModel, 1)
    if row is None or row.mode not in MODES:
        return Gate()
    opens = row.opens_at.replace(tzinfo=UTC) if row.opens_at else None
    return Gate(row.mode, opens)


def write(session: Session, mode: str, opens_at: datetime | None = None) -> Gate:
    if mode not in MODES:
        raise ValueError(f"porte : état inconnu {mode!r}")
    naive = opens_at.astimezone(UTC).replace(tzinfo=None) if opens_at else None
    with atomic(session):
        row = session.get(EntryGateModel, 1)
        now = datetime.now(UTC).replace(tzinfo=None)
        if row is None:
            session.add(EntryGateModel(id=1, mode=mode, opens_at=naive, changed_at=now))
        else:
            row.mode, row.opens_at, row.changed_at = mode, naive, now
    return read(session)
