"""Tutoriel `/tuto` : progression du joueur, vérification des actions et
récompense de fin (3 potions du Grand Cerisier, une seule fois).

Règles et textes : `app/domain/services/tutorial_service.py`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.services import tutorial_service as tsvc
from app.infrastructure.db.models.player_career_stats_model import PlayerCareerStatsModel
from app.infrastructure.db.models.element_affinity_model import PlayerElementAffinityModel
from app.infrastructure.db.models.progression_model import PlayerProgressionModel
from app.infrastructure.db.models.tutorial_model import PlayerTutorialModel
from app.infrastructure.db.repositories.cooldown_repository import CooldownRepository
from app.infrastructure.db.repositories.inventory_repository import InventoryRepository
from app.infrastructure.db.repositories.item_repository import ItemRepository
from app.infrastructure.db.unit_of_work import atomic
from app.shared.enums import CooldownAction


@dataclass(frozen=True)
class TutorialState:
    status: str          # "en_cours", "passe", "termine"
    step: int
    rewarded: bool


def _row(session: Session, player_id: int) -> PlayerTutorialModel:
    row = session.get(PlayerTutorialModel, player_id)
    if row is None:
        row = PlayerTutorialModel(player_id=player_id, status="en_cours", step=0)
        session.add(row)
        session.flush()
    return row


def state(session: Session, player_id: int) -> TutorialState:
    row = session.get(PlayerTutorialModel, player_id)
    if row is None:
        return TutorialState("en_cours", 0, False)
    return TutorialState(row.status, row.step, row.rewarded_at is not None)


def go_to(session: Session, player_id: int, step: int) -> None:
    """Retient l'étape où en est le joueur (il reprend là au prochain /tuto)."""
    with atomic(session):
        row = _row(session, player_id)
        row.step = max(0, min(step, len(tsvc.STEPS) - 1))
        if row.status == "passe":
            row.status = "en_cours"
        row.updated_at = datetime.now(UTC).replace(tzinfo=None)


def skip(session: Session, player_id: int) -> None:
    """Le joueur passe le tutoriel dès le début (il pourra y revenir)."""
    with atomic(session):
        row = _row(session, player_id)
        if row.status != "termine":
            row.status = "passe"
        row.updated_at = datetime.now(UTC).replace(tzinfo=None)


def finish(session: Session, player_id: int) -> int:
    """Fin du tutoriel : la récompense, UNE fois par joueur. Renvoie le
    nombre de potions données (0 si déjà reçues)."""
    with atomic(session):
        row = _row(session, player_id)
        row.status = "termine"
        row.updated_at = datetime.now(UTC).replace(tzinfo=None)
        if row.rewarded_at is not None:
            return 0
        item = ItemRepository(session).get_by_code(tsvc.REWARD_ITEM)
        if item is None:
            return 0
        InventoryRepository(session).add_item(player_id, item.id, tsvc.REWARD_QUANTITY, commit=False)
        row.rewarded_at = row.updated_at
        return tsvc.REWARD_QUANTITY


# ------------------------------------------------------------ vérifications
def _daily(session: Session, player_id: int) -> bool:
    return CooldownRepository(session).get_by_player_and_action(player_id, CooldownAction.DAILY.value) is not None


def _stats(session: Session, player_id: int) -> bool:
    prog = session.get(PlayerProgressionModel, player_id)
    if prog is None:
        return True
    placed = prog.points_attack + prog.points_defense + prog.points_max_hp
    return placed > 0 or prog.stat_points <= 0      # rien à placer : l'étape est faite


def _combat(session: Session, player_id: int) -> bool:
    career = session.get(PlayerCareerStatsModel, player_id)
    return career is not None and career.combats_fought > 0


def _voyante(session: Session, player_id: int) -> bool:
    return session.execute(select(PlayerElementAffinityModel.player_id).where(
        PlayerElementAffinityModel.player_id == player_id,
        PlayerElementAffinityModel.revealed.is_(True)).limit(1)).first() is not None


CHECKS = {"daily": _daily, "stats": _stats, "combat": _combat, "voyante": _voyante}


def check(session: Session, player_id: int, step: tsvc.TutorialStep) -> bool:
    """L'action de l'étape est-elle faite ? (toujours vrai sans vérification)."""
    fn = CHECKS.get(step.check)
    return True if fn is None else bool(fn(session, player_id))
