"""Épreuves de rôle (`/defi`) : meilleur score du jour et semaines clôturées."""

from datetime import UTC, date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.db.base import Base


class RoleTrialScoreModel(Base):
    """UNE ligne par (joueur, jour, rôle) : le MEILLEUR score du jour."""

    __tablename__ = "role_trial_scores"
    __table_args__ = (UniqueConstraint("player_id", "day", "role", name="uq_role_trial_day"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), index=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    role: Mapped[str] = mapped_column(String(10))
    variant_code: Mapped[str] = mapped_column(String(30))
    score: Mapped[int] = mapped_column(Integer, default=0)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))


class RoleTrialWeekModel(Base):
    """Semaine CLÔTURÉE (titres et or distribués) — garantit qu'on ne paie
    qu'une fois, même si le bot redémarre pendant la clôture."""

    __tablename__ = "role_trial_weeks"

    week_start: Mapped[date] = mapped_column(Date, primary_key=True)
    settled_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    results_json: Mapped[str] = mapped_column(Text, default="{}")
