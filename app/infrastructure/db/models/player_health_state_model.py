from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.db.base import Base


class PlayerHealthStateModel(Base):
    __tablename__ = "player_health_states"

    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"), primary_key=True)
    current_hp: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)