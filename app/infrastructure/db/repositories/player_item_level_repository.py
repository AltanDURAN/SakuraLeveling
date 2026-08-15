"""Repository des niveaux de forge d'équipement (par joueur × item_definition)."""

from __future__ import annotations

from datetime import datetime, UTC

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.infrastructure.db.models.player_item_level_model import PlayerItemLevelModel


class PlayerItemLevelRepository:
    def __init__(self, session: Session):
        self.session = session

    def get_level(self, player_id: int, item_definition_id: int) -> int:
        stmt = select(PlayerItemLevelModel.level).where(
            PlayerItemLevelModel.player_id == player_id,
            PlayerItemLevelModel.item_definition_id == item_definition_id,
        )
        return self.session.execute(stmt).scalar_one_or_none() or 0

    def get_levels_for_player(self, player_id: int) -> dict[int, int]:
        stmt = select(
            PlayerItemLevelModel.item_definition_id, PlayerItemLevelModel.level
        ).where(PlayerItemLevelModel.player_id == player_id)
        return {row[0]: row[1] for row in self.session.execute(stmt).all()}

    def get_levels_for_players(
        self, player_ids: list[int]
    ) -> dict[int, dict[int, int]]:
        """Variante EN LOT : une seule requête pour N joueurs (anti N+1)."""
        if not player_ids:
            return {}
        stmt = select(
            PlayerItemLevelModel.player_id,
            PlayerItemLevelModel.item_definition_id,
            PlayerItemLevelModel.level,
        ).where(PlayerItemLevelModel.player_id.in_(player_ids))
        out: dict[int, dict[int, int]] = {pid: {} for pid in player_ids}
        for pid, item_id, level in self.session.execute(stmt).all():
            out.setdefault(pid, {})[item_id] = level
        return out

    def increment(
        self, player_id: int, item_definition_id: int, max_level: int
    ) -> int:
        """+1 niveau (borné à max_level). Retourne le nouveau niveau, ou -1 si
        déjà au max (aucune modification)."""
        stmt = select(PlayerItemLevelModel).where(
            PlayerItemLevelModel.player_id == player_id,
            PlayerItemLevelModel.item_definition_id == item_definition_id,
        )
        row = self.session.execute(stmt).scalar_one_or_none()
        if row is None:
            row = PlayerItemLevelModel(
                player_id=player_id,
                item_definition_id=item_definition_id,
                level=1,
            )
            self.session.add(row)
            self.session.flush()
            return 1
        if row.level >= max_level:
            return -1
        row.level += 1
        row.updated_at = datetime.now(UTC)
        self.session.flush()
        return row.level
