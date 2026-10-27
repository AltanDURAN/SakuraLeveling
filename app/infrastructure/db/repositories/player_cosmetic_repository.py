"""Cosmétiques portés par un joueur (`player_cosmetics`)."""

from __future__ import annotations

from datetime import datetime, UTC

from sqlalchemy.orm import Session

from app.infrastructure.db.models.player_cosmetic_model import PlayerCosmeticModel
from app.infrastructure.db.unit_of_work import commit

#: Emplacements d'apparence (colonnes de `player_cosmetics`).
COSMETIC_SLOTS: tuple[str, ...] = ("fond", "cadre", "titre")


class PlayerCosmeticRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, player_id: int) -> dict[str, str]:
        """{emplacement: code} des cosmétiques portés (absents = défaut)."""
        row = self.session.get(PlayerCosmeticModel, player_id)
        if row is None:
            return {}
        return {slot: getattr(row, slot) for slot in COSMETIC_SLOTS if getattr(row, slot)}

    def set(self, player_id: int, slot: str, code: str | None) -> None:
        if slot not in COSMETIC_SLOTS:
            raise ValueError(f"emplacement inconnu : {slot}")
        row = self.session.get(PlayerCosmeticModel, player_id)
        if row is None:
            row = PlayerCosmeticModel(player_id=player_id)
            self.session.add(row)
        setattr(row, slot, code or None)
        row.updated_at = datetime.now(UTC)
        commit(self.session)
