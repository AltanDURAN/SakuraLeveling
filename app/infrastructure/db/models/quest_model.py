from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.db.base import Base


class QuestDefinitionModel(Base):
    __tablename__ = "quest_definitions"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(String(255), default="")

    objective_type: Mapped[str] = mapped_column(String(50))
    target_code: Mapped[str] = mapped_column(String(100))
    required_quantity: Mapped[int] = mapped_column(Integer)

    reward_gold: Mapped[int] = mapped_column(Integer, default=0)
    reward_xp: Mapped[int] = mapped_column(Integer, default=0)
    reward_items_json: Mapped[list | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)


class PlayerQuestStateModel(Base):
    __tablename__ = "player_quest_states"
    __table_args__ = (
        UniqueConstraint("player_id", "quest_definition_id", name="uq_player_quest"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"), index=True)
    quest_definition_id: Mapped[int] = mapped_column(
        ForeignKey("quest_definitions.id"),
        index=True,
    )

    progress_quantity: Mapped[int] = mapped_column(Integer, default=0)
    is_completed: Mapped[bool] = mapped_column(Boolean, default=False)
    is_claimed: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)