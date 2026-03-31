from datetime import datetime, UTC

from sqlalchemy import ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.db.base import Base


class PlayerResourceModel(Base):
    __tablename__ = "player_resources"

    player_id: Mapped[int] = mapped_column(
        ForeignKey("players.id"), primary_key=True
    )

    gold: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(default=datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(default=datetime.now(UTC))

    player = relationship("PlayerModel", back_populates="resources")