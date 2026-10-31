"""Tutoriel `/tuto` : où en est chaque joueur, et s'il a déjà reçu sa récompense."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.db.base import Base


class PlayerTutorialModel(Base):
    __tablename__ = "player_tutorials"

    player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), primary_key=True)
    #: "en_cours", "passe" (passé dès le début) ou "termine".
    status: Mapped[str] = mapped_column(String(20), default="en_cours", server_default="en_cours")
    step: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    rewarded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
