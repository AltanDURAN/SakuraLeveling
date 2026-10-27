"""Progression de la tour solo : une ligne par joueur.

`best_floor` = dernier étage FRANCHI (0 = aucun). La progression est
permanente : une défaite ne la fait jamais baisser (décision de l'auteur,
27/10/2026). `best_at` départage le classement (premier arrivé).
"""

from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.db.base import Base


class PlayerTowerProgressModel(Base):
    __tablename__ = "player_tower_progress"

    player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), primary_key=True)
    best_floor: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    wins: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    daily_claimed_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    best_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
