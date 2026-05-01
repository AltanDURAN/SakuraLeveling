from datetime import datetime, UTC

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.infrastructure.db.models.mob_model import MobDefinitionModel
from app.infrastructure.db.models.player_mob_kill_model import PlayerMobKillModel
from app.infrastructure.db.models.player_model import PlayerModel


class PlayerKillRepository:
    def __init__(self, session: Session):
        self.session = session

    def increment(self, player_id: int, mob_code: str, amount: int = 1) -> None:
        stmt = select(PlayerMobKillModel).where(
            PlayerMobKillModel.player_id == player_id,
            PlayerMobKillModel.mob_code == mob_code,
        )
        model = self.session.execute(stmt).scalar_one_or_none()

        now = datetime.now(UTC)

        if model is None:
            model = PlayerMobKillModel(
                player_id=player_id,
                mob_code=mob_code,
                kill_count=amount,
                created_at=now,
                updated_at=now,
            )
            self.session.add(model)
        else:
            model.kill_count += amount
            model.updated_at = now

        self.session.commit()

    def get_total_kills(self, player_id: int) -> int:
        stmt = select(func.coalesce(func.sum(PlayerMobKillModel.kill_count), 0)).where(
            PlayerMobKillModel.player_id == player_id,
        )
        return int(self.session.execute(stmt).scalar() or 0)

    def get_kills_per_mob(self, player_id: int) -> dict[str, int]:
        stmt = select(PlayerMobKillModel.mob_code, PlayerMobKillModel.kill_count).where(
            PlayerMobKillModel.player_id == player_id,
        )
        return {row[0]: row[1] for row in self.session.execute(stmt).all()}

    def get_kills_for_family(self, player_id: int, family: str) -> int:
        stmt = (
            select(func.coalesce(func.sum(PlayerMobKillModel.kill_count), 0))
            .join(MobDefinitionModel, PlayerMobKillModel.mob_code == MobDefinitionModel.code)
            .where(
                PlayerMobKillModel.player_id == player_id,
                MobDefinitionModel.family == family,
            )
        )
        return int(self.session.execute(stmt).scalar() or 0)

    def top_total_kills(self, limit: int = 10) -> list[tuple[int, str, int]]:
        stmt = (
            select(
                PlayerModel.id,
                PlayerModel.display_name,
                func.coalesce(func.sum(PlayerMobKillModel.kill_count), 0).label("total"),
            )
            .join(PlayerMobKillModel, PlayerMobKillModel.player_id == PlayerModel.id)
            .group_by(PlayerModel.id, PlayerModel.display_name)
            .order_by(func.sum(PlayerMobKillModel.kill_count).desc())
            .limit(limit)
        )
        return [(row[0], row[1], int(row[2] or 0)) for row in self.session.execute(stmt).all()]

    def top_kills_for_mob(self, mob_code: str, limit: int = 10) -> list[tuple[int, str, int]]:
        stmt = (
            select(
                PlayerModel.id,
                PlayerModel.display_name,
                PlayerMobKillModel.kill_count,
            )
            .join(PlayerMobKillModel, PlayerMobKillModel.player_id == PlayerModel.id)
            .where(PlayerMobKillModel.mob_code == mob_code)
            .order_by(PlayerMobKillModel.kill_count.desc())
            .limit(limit)
        )
        return [(row[0], row[1], int(row[2])) for row in self.session.execute(stmt).all()]

    def top_kills_for_family(self, family: str, limit: int = 10) -> list[tuple[int, str, int]]:
        stmt = (
            select(
                PlayerModel.id,
                PlayerModel.display_name,
                func.coalesce(func.sum(PlayerMobKillModel.kill_count), 0).label("total"),
            )
            .join(PlayerMobKillModel, PlayerMobKillModel.player_id == PlayerModel.id)
            .join(MobDefinitionModel, PlayerMobKillModel.mob_code == MobDefinitionModel.code)
            .where(MobDefinitionModel.family == family)
            .group_by(PlayerModel.id, PlayerModel.display_name)
            .order_by(func.sum(PlayerMobKillModel.kill_count).desc())
            .limit(limit)
        )
        return [(row[0], row[1], int(row[2] or 0)) for row in self.session.execute(stmt).all()]
