from datetime import datetime, timezone

from sqlalchemy import ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.db.base import Base


class PlayerProgressionModel(Base):
    __tablename__ = "player_progressions"

    player_id: Mapped[int] = mapped_column(
        ForeignKey("players.id"), primary_key=True
    )

    level: Mapped[int] = mapped_column(Integer, default=1)
    xp: Mapped[int] = mapped_column(Integer, default=0)
    skill_points: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(default=datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(default=datetime.now(timezone.utc))

    player = relationship("PlayerModel", back_populates="progression")