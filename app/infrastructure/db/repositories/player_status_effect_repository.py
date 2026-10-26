"""Repository des effets temporaires (buff/debuff) des joueurs."""

from __future__ import annotations

from datetime import datetime, timedelta, UTC

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.infrastructure.db.models.player_status_effect_model import (
    PlayerStatusEffectModel,
)


#: `kind` des effets d'événement (multiplicateur global, petite fille).
ALL_STATS_KIND = "all_stats_pct"
#: Préfixe des élixirs d'Elna (cf. alchemy_service.ELIXIR_STATUS_KINDS).
ELIXIR_PREFIX = "elixir_"
REGEN_KIND = "elixir_regen"


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
        """Multiplicateurs « toutes stats » NON expirés (événements). Les
        élixirs ont leur propre lecture (`list_active_elixirs`) : ils ne
        comptent pas partout."""
        stmt = select(PlayerStatusEffectModel.multiplier).where(
            PlayerStatusEffectModel.player_id == player_id,
            PlayerStatusEffectModel.kind == ALL_STATS_KIND,
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
            PlayerStatusEffectModel.kind == ALL_STATS_KIND,
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

    # ------------------------------------------------------------ élixirs --
    def list_active_elixirs(self, player_id: int) -> dict[str, PlayerStatusEffectModel]:
        """{kind: effet} des élixirs actifs (un par effet, cf. apply_elixir)."""
        stmt = select(PlayerStatusEffectModel).where(
            PlayerStatusEffectModel.player_id == player_id,
            PlayerStatusEffectModel.kind.like(f"{ELIXIR_PREFIX}%"),
            PlayerStatusEffectModel.expires_at > _now(),
        )
        return {e.kind: e for e in self.session.execute(stmt).scalars().all()}

    def apply_elixir(self, player_id: int, code: str, kind: str, multiplier: float,
                     duration_seconds: int) -> tuple[PlayerStatusEffectModel, bool]:
        """Un MÊME effet ne se cumule jamais : s'il est actif à la même force,
        sa durée repart de zéro (renouvelé = True) ; plus fort, il le remplace
        (l'ancien s'arrête maintenant : la fenêtre de récupération garde son
        ancien multiplicateur jusque-là) ; sinon un nouvel effet commence.
        Un élixir PLUS FAIBLE que l'actif est refusé en amont (UseConsumable)."""
        now = _now()
        active = self.list_active_elixirs(player_id).get(kind)
        if active is not None and float(active.multiplier) == float(multiplier):
            active.expires_at = now + timedelta(seconds=max(1, int(duration_seconds)))
            active.code = code
            self.session.flush()
            return active, True
        if active is not None:
            active.expires_at = now
        effect = PlayerStatusEffectModel(
            player_id=player_id, code=code, kind=kind, multiplier=float(multiplier),
            expires_at=now + timedelta(seconds=max(1, int(duration_seconds))),
            created_at=now,
        )
        self.session.add(effect)
        self.session.flush()
        return effect, False

    def regen_windows(self, player_id: int) -> list[tuple[datetime, datetime, float]]:
        """Fenêtres (début, fin, ×M) des élixirs de récupération, y compris
        expirés depuis peu : la régénération est calculée après coup."""
        stmt = select(PlayerStatusEffectModel).where(
            PlayerStatusEffectModel.player_id == player_id,
            PlayerStatusEffectModel.kind == REGEN_KIND,
        )
        return [(e.created_at, e.expires_at, float(e.multiplier))
                for e in self.session.execute(stmt).scalars().all()]

    def purge_expired(self) -> int:
        """Supprime les effets expirés depuis plus d'un jour (un élixir de
        récupération doit encore compter au prochain calcul de régénération)."""
        result = self.session.execute(
            delete(PlayerStatusEffectModel).where(
                PlayerStatusEffectModel.expires_at <= _now() - timedelta(days=1)
            )
        )
        return result.rowcount or 0

    def clear_for_player(self, player_id: int) -> None:
        self.session.execute(
            delete(PlayerStatusEffectModel).where(
                PlayerStatusEffectModel.player_id == player_id
            )
        )
