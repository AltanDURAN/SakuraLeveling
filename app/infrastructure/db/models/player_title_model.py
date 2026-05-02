from datetime import datetime, UTC

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.db.base import Base


class PlayerTitleModel(Base):
    __tablename__ = "player_titles"
    __table_args__ = (
        UniqueConstraint("player_id", "title_code", name="uq_player_title_code"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    player_id: Mapped[int] = mapped_column(
        ForeignKey("players.id", ondelete="CASCADE"), index=True
    )
    title_code: Mapped[str] = mapped_column(String(100))
    unlocked_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC)
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
