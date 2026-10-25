from datetime import datetime, UTC

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.db.base import Base


class WeeklyQuestAssignmentModel(Base):
    __tablename__ = "weekly_quest_assignments"
    __table_args__ = (
        UniqueConstraint(
            "player_id", "week_start", "quest_code",
            name="uq_weekly_quest_assignment",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    player_id: Mapped[int] = mapped_column(
        ForeignKey("players.id", ondelete="CASCADE"), index=True
    )
    week_start: Mapped[datetime] = mapped_column(DateTime, index=True)
    quest_code: Mapped[str] = mapped_column(String(100))
    # Quête CONCRÈTE tirée pour ce joueur (25/10/2026) : objectif, cible et
    # quantité adaptés à sa zone, son niveau et son rôle — figés au tirage.
    name: Mapped[str] = mapped_column(String(120), default="")
    description: Mapped[str] = mapped_column(String(300), default="")
    tier: Mapped[str] = mapped_column(String(10), default="easy")
    objective_type: Mapped[str] = mapped_column(String(40), default="")
    objective_target: Mapped[str] = mapped_column(String(100), default="")
    objective_quantity: Mapped[int] = mapped_column(Integer, default=1)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    completed: Mapped[bool] = mapped_column(Boolean, default=False)
    claimed: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
