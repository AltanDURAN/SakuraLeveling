from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.db.base import Base


class PlayerCooldownModel(Base):
    __tablename__ = "player_cooldowns"
    __table_args__ = (
        UniqueConstraint("player_id", "action_key", name="uq_player_cooldown_action"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"), index=True)
    action_key: Mapped[str] = mapped_column(String(100), index=True)

    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    next_available_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(default=datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(default=datetime.now(timezone.utc))