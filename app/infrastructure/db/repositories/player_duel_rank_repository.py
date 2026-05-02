"""Repository pour le classement de duels 1v1.

Convention : `rank_position` ≥ 1, plus petit = mieux classé. Le `get_or_create`
attribue au nouveau venu la pire position connue + 1 (= bottom of ladder), de
sorte qu'un joueur ne soit jamais privilégié à l'inscription. La position 1
reste donc toujours occupée par celui qui a vaincu tous les autres.
"""

from datetime import datetime, UTC

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.entities.duel_rank import DuelRank
from app.infrastructure.db.models.player_duel_rank_model import PlayerDuelRankModel


class PlayerDuelRankRepository:
    def __init__(self, session: Session):
        self.session = session

    # ---------- lecture ----------

    def get_by_player_id(self, player_id: int) -> DuelRank | None:
        stmt = select(PlayerDuelRankModel).where(
            PlayerDuelRankModel.player_id == player_id
        )
        model = self.session.execute(stmt).scalar_one_or_none()
        return self._to_domain(model) if model else None

    def list_top(self, limit: int = 10) -> list[DuelRank]:
        stmt = (
            select(PlayerDuelRankModel)
            .order_by(PlayerDuelRankModel.rank_position.asc())
            .limit(limit)
        )
        return [self._to_domain(m) for m in self.session.execute(stmt).scalars().all()]

    def list_all(self) -> list[DuelRank]:
        stmt = select(PlayerDuelRankModel).order_by(
            PlayerDuelRankModel.rank_position.asc()
        )
        return [self._to_domain(m) for m in self.session.execute(stmt).scalars().all()]

    # ---------- écriture ----------

    def get_or_create(self, player_id: int) -> DuelRank:
        existing = self.session.execute(
            select(PlayerDuelRankModel).where(
                PlayerDuelRankModel.player_id == player_id
            )
        ).scalar_one_or_none()
        if existing is not None:
            return self._to_domain(existing)

        max_pos = self.session.execute(
            select(func.max(PlayerDuelRankModel.rank_position))
        ).scalar()
        next_pos = (max_pos or 0) + 1

        now = datetime.now(UTC)
        model = PlayerDuelRankModel(
            player_id=player_id,
            rank_position=next_pos,
            wins=0,
            losses=0,
            created_at=now,
            updated_at=now,
        )
        self.session.add(model)
        self.session.commit()
        return self._to_domain(model)

    def swap_positions(self, player_a_id: int, player_b_id: int) -> None:
        """Échange les rank_position de deux joueurs. Atomique (commit final)."""
        a = self.session.execute(
            select(PlayerDuelRankModel).where(
                PlayerDuelRankModel.player_id == player_a_id
            )
        ).scalar_one()
        b = self.session.execute(
            select(PlayerDuelRankModel).where(
                PlayerDuelRankModel.player_id == player_b_id
            )
        ).scalar_one()

        # Étape via valeur sentinelle pour éviter le conflit d'unicité éventuel
        # si on ajoute plus tard un UNIQUE sur rank_position. Aujourd'hui pas
        # contraint mais on prépare le terrain.
        a_pos, b_pos = a.rank_position, b.rank_position
        now = datetime.now(UTC)
        a.rank_position = -1
        self.session.flush()
        b.rank_position = a_pos
        self.session.flush()
        a.rank_position = b_pos
        a.updated_at = now
        b.updated_at = now
        self.session.commit()

    def increment_wins(self, player_id: int) -> None:
        model = self.session.execute(
            select(PlayerDuelRankModel).where(
                PlayerDuelRankModel.player_id == player_id
            )
        ).scalar_one()
        model.wins += 1
        model.updated_at = datetime.now(UTC)
        self.session.commit()

    def increment_losses(self, player_id: int) -> None:
        model = self.session.execute(
            select(PlayerDuelRankModel).where(
                PlayerDuelRankModel.player_id == player_id
            )
        ).scalar_one()
        model.losses += 1
        model.updated_at = datetime.now(UTC)
        self.session.commit()

    def delete_for_player(self, player_id: int) -> None:
        """Supprime la ligne d'un joueur (utilisé par /admin reset_player).

        Les autres positions ne sont pas re-compactées : un trou peut donc
        exister temporairement (ex : positions 1, 2, 4 si le 3 est reset).
        Acceptable — le ladder reste cohérent (asc), et la prochaine fois
        qu'un joueur est inscrit il prend max+1.
        """
        model = self.session.execute(
            select(PlayerDuelRankModel).where(
                PlayerDuelRankModel.player_id == player_id
            )
        ).scalar_one_or_none()
        if model is not None:
            self.session.delete(model)
            self.session.commit()

    # ---------- conversion ----------

    def _to_domain(self, model: PlayerDuelRankModel) -> DuelRank:
        return DuelRank(
            player_id=model.player_id,
            rank_position=model.rank_position,
            wins=model.wins,
            losses=model.losses,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )
