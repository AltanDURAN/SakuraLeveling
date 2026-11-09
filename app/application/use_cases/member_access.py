"""Où en est un compte Discord dans le parcours d'arrivée (08/11/2026).

Deux étapes, retenues par COMPTE (elles survivent au reset d'un joueur ; le
reset de saison les vide, chacun repart du règlement) :
  • le règlement accepté (`rules_acceptances`) → Rang F ;
  • l'aventure commencée, tutoriel fini ou passé (`adventurers`) → Aventurier.
Les rôles Discord eux-mêmes sont donnés par le bot (`app/bot/access.py`).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.infrastructure.db.models.adventurer_model import AdventurerModel
from app.infrastructure.db.models.rules_model import RulesAcceptanceModel
from app.infrastructure.db.unit_of_work import atomic


@dataclass(frozen=True)
class MemberAccess:
    #: Règlement accepté, quelle que soit la version : une nouvelle version
    #: redemande l'acceptation aux commandes, elle ne ferme aucun salon.
    accepted: bool = False
    #: Tutoriel fini ou passé.
    adventurer: bool = False


def access(session: Session, discord_id: int) -> MemberAccess:
    return MemberAccess(
        accepted=session.get(RulesAcceptanceModel, discord_id) is not None,
        adventurer=session.get(AdventurerModel, discord_id) is not None,
    )


def all_access(session: Session) -> dict[int, MemberAccess]:
    """Tous les comptes qui ont franchi au moins une étape."""
    accepted = set(session.execute(select(RulesAcceptanceModel.discord_id)).scalars())
    adventurers = set(session.execute(select(AdventurerModel.discord_id)).scalars())
    return {discord_id: MemberAccess(discord_id in accepted, discord_id in adventurers)
            for discord_id in accepted | adventurers}


def mark_adventurer(session: Session, discord_id: int, how: str) -> bool:
    """Retient que ce compte a commencé l'aventure. False s'il l'avait déjà
    fait (la première date reste)."""
    with atomic(session):
        if session.get(AdventurerModel, discord_id) is not None:
            return False
        session.add(AdventurerModel(discord_id=discord_id, how=how,
                                    started_at=datetime.now(UTC).replace(tzinfo=None)))
        return True
