"""Les « premières fois » d'un joueur, annoncées dans le salon général
(décision de l'auteur, 14/11/2026) : première pièce épique, première élite
vaincue, premier étage 10 de la tour.

Une première fois est retenue dans le journal (`game_events`, kind
`milestone`) : elle ne s'annonce qu'une fois par saison (le journal repart à
zéro au lancement d'une saison)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.infrastructure.db.models.monitoring_model import GameEventModel
from app.infrastructure.db.session import get_db_session
from app.infrastructure.monitoring import telemetry

KIND = "milestone"
FIRST_EPIC = "premiere_epique"
FIRST_ELITE = "premiere_elite"
TOWER_10 = "tour_10"
#: Raretés qui comptent comme « épique ou mieux ».
EPIC_OR_BETTER = frozenset({"epic", "legendary", "mythic"})


def claim(session: Session, player_id: int, ref: str) -> bool:
    """True la PREMIÈRE fois que ce joueur atteint ce jalon (et le retient).
    Ne valide pas la transaction ; jamais d'exception."""
    try:
        seen = session.execute(
            select(GameEventModel.id).where(GameEventModel.kind == KIND, GameEventModel.player_id == player_id,
                                            GameEventModel.ref == ref).limit(1)).first()
        if seen is not None:
            return False
        telemetry.record(session, KIND, player_id=player_id, ref=ref)
        return True
    except Exception:  # noqa: BLE001 — une annonce ne casse jamais un combat
        return False


def claim_now(player_ids: list[int], ref: str) -> set[int]:
    """Ceux de `player_ids` pour qui c'est la première fois (sa propre transaction)."""
    if not player_ids:
        return set()
    try:
        with get_db_session() as session:
            first = {pid for pid in player_ids if claim(session, pid, ref)}
            session.commit()
            return first
    except Exception:  # noqa: BLE001
        return set()
