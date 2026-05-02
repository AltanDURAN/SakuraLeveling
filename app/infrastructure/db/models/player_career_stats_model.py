from datetime import datetime, UTC

from sqlalchemy import ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.db.base import Base


class PlayerCareerStatsModel(Base):
    __tablename__ = "player_career_stats"

    player_id: Mapped[int] = mapped_column(
        ForeignKey("players.id", ondelete="CASCADE"),
        primary_key=True,
    )

    gold_earned_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    damage_dealt_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    damage_tanked_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    hp_healed_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    combats_fought: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    combats_won: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    combats_lost: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
