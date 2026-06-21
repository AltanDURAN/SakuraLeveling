"""Suppression en cascade d'un mob : retire la définition ET ses références
en base (compteurs de kills des joueurs).

Le nettoyage de mobs.json est géré côté webapp (content_sync).
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.infrastructure.db.models.mob_model import MobDefinitionModel
from app.infrastructure.db.models.player_mob_kill_model import PlayerMobKillModel


@dataclass
class DeleteMobResult:
    deleted: bool
    code: str
    kills_removed: int = 0


class DeleteMobUseCase:
    def execute(self, session: Session, code: str) -> DeleteMobResult:
        mob = session.execute(
            select(MobDefinitionModel).where(MobDefinitionModel.code == code)
        ).scalar_one_or_none()
        if mob is None:
            return DeleteMobResult(deleted=False, code=code)

        res = session.execute(
            delete(PlayerMobKillModel).where(PlayerMobKillModel.mob_code == code)
        )
        session.delete(mob)
        session.commit()
        return DeleteMobResult(deleted=True, code=code, kills_removed=res.rowcount or 0)
