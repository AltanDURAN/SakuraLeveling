"""Repository des effets temporaires (buff/debuff) des joueurs."""

from __future__ import annotations

from datetime import datetime, timedelta, UTC

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.infrastructure.db.models.player_status_effect_model import (
    PlayerStatusEffectModel,
)


def _now() -> datetime:
    # DateTime SQLite est stocké naïf ; on compare en naïf UTC.
    return datetime.now(UTC).replace(tzinfo=None)


class PlayerStatusEffectRepository:
    def __init__(self, session: Session):
        self.session = session

    def add(
        self,
        player_id: int,
        code: str,
        multiplier: float,
        duration_seconds: int,
        kind: str = "all_stats_pct",
    ) -> PlayerStatusEffectModel:
        effect = PlayerStatusEffectModel(
            player_id=player_id,
            code=code,
            kind=kind,
            multiplier=float(multiplier),
            expires_at=_now() + timedelta(seconds=max(1, int(duration_seconds))),
        )
        self.session.add(effect)
        self.session.flush()
        return effect

    def list_active_multipliers(self, player_id: int) -> list[float]:
        """Multiplicateurs des effets NON expirés (pour l'agrégation stats)."""
        stmt = select(PlayerStatusEffectModel.multiplier).where(
            PlayerStatusEffectModel.player_id == player_id,
            PlayerStatusEffectModel.expires_at > _now(),
        )
        return [row[0] for row in self.session.execute(stmt).all()]

    def list_active_multipliers_bulk(
        self, player_ids: list[int]
    ) -> dict[int, list[float]]:
        """Variante EN LOT : une seule requête pour N joueurs (anti N+1)."""
        if not player_ids:
            return {}
        stmt = select(
            PlayerStatusEffectModel.player_id, PlayerStatusEffectModel.multiplier
        ).where(
            PlayerStatusEffectModel.player_id.in_(player_ids),
            PlayerStatusEffectModel.expires_at > _now(),
        )
        out: dict[int, list[float]] = {pid: [] for pid in player_ids}
        for pid, mult in self.session.execute(stmt).all():
            out.setdefault(pid, []).append(mult)
        return out

    def list_active(self, player_id: int) -> list[PlayerStatusEffectModel]:
        stmt = select(PlayerStatusEffectModel).where(
            PlayerStatusEffectModel.player_id == player_id,
            PlayerStatusEffectModel.expires_at > _now(),
        )
        return list(self.session.execute(stmt).scalars().all())

    def purge_expired(self) -> int:
        result = self.session.execute(
            delete(PlayerStatusEffectModel).where(
                PlayerStatusEffectModel.expires_at <= _now()
            )
        )
        return result.rowcount or 0

    def clear_for_player(self, player_id: int) -> None:
        self.session.execute(
            delete(PlayerStatusEffectModel).where(
                PlayerStatusEffectModel.player_id == player_id
            )
        )
