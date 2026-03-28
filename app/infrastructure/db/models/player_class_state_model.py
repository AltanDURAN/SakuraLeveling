from datetime import datetime

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.db.base import Base


class PlayerClassStateModel(Base):
    __tablename__ = "player_class_states"

    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"), primary_key=True)
    current_class_id: Mapped[int | None] = mapped_column(
        ForeignKey("class_definitions.id"),
        nullable=True,
    )
    unlocked_at: Mapped[datetime | None] = mapped_column(nullable=True)

    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)