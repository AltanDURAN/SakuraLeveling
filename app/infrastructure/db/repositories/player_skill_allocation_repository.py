from datetime import datetime, UTC

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.infrastructure.db.models.player_skill_allocation_model import (
    PlayerSkillAllocationModel,
)


class PlayerSkillAllocationRepository:
    def __init__(self, session: Session):
        self.session = session

    def list_by_player(self, player_id: int) -> dict[str, int]:
        """Retourne {skill_code: level} pour les skills à level > 0."""
        stmt = select(PlayerSkillAllocationModel).where(
            PlayerSkillAllocationModel.player_id == player_id,
            PlayerSkillAllocationModel.level > 0,
        )
        rows = self.session.execute(stmt).scalars().all()
        return {row.skill_code: row.level for row in rows}

    def list_by_players(self, player_ids: list[int]) -> dict[int, dict[str, int]]:
        """Variante EN LOT de `list_by_player` : une seule requête pour N joueurs.
        Évite le N+1 du leaderboard (cf. audit §5)."""
        if not player_ids:
            return {}
        stmt = select(PlayerSkillAllocationModel).where(
            PlayerSkillAllocationModel.player_id.in_(player_ids),
            PlayerSkillAllocationModel.level > 0,
        )
        out: dict[int, dict[str, int]] = {pid: {} for pid in player_ids}
        for row in self.session.execute(stmt).scalars().all():
            out.setdefault(row.player_id, {})[row.skill_code] = row.level
        return out

    def upsert_level(self, player_id: int, skill_code: str, level: int) -> None:
        stmt = select(PlayerSkillAllocationModel).where(
            PlayerSkillAllocationModel.player_id == player_id,
            PlayerSkillAllocationModel.skill_code == skill_code,
        )
        model = self.session.execute(stmt).scalar_one_or_none()
        now = datetime.now(UTC)

        if model is None:
            model = PlayerSkillAllocationModel(
                player_id=player_id,
                skill_code=skill_code,
                level=level,
                created_at=now,
                updated_at=now,
            )
            self.session.add(model)
        else:
            model.level = level
            model.updated_at = now

        self.session.commit()

    def delete_for_player(self, player_id: int) -> None:
        self.session.execute(
            delete(PlayerSkillAllocationModel).where(
                PlayerSkillAllocationModel.player_id == player_id
            )
        )
        self.session.commit()
