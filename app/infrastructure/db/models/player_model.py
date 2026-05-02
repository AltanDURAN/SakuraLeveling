from datetime import datetime, UTC

from sqlalchemy import BigInteger, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.db.base import Base


class PlayerModel(Base):
    __tablename__ = "players"

    id: Mapped[int] = mapped_column(primary_key=True)
    discord_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)

    username: Mapped[str] = mapped_column(String(100))
    display_name: Mapped[str] = mapped_column(String(100))

    created_at: Mapped[datetime] = mapped_column(default=datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(default=datetime.now(UTC))
    last_seen_at: Mapped[datetime] = mapped_column(default=datetime.now(UTC))

    progression = relationship(
        "PlayerProgressionModel",
        back_populates="player",
        uselist=False,
        cascade="all, delete-orphan",
    )

    resources = relationship(
        "PlayerResourceModel",
        back_populates="player",
        uselist=False,
        cascade="all, delete-orphan",
    )