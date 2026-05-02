from datetime import datetime, UTC

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.db.base import Base


class WorldBossModel(Base):
    __tablename__ = "world_bosses"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(100))
    name: Mapped[str] = mapped_column(String(100))
    image_name: Mapped[str] = mapped_column(String(255), default="")

    max_hp: Mapped[int] = mapped_column(Integer)
    current_hp: Mapped[int] = mapped_column(Integer)
    attack: Mapped[int] = mapped_column(Integer)
    defense: Mapped[int] = mapped_column(Integer)
    speed: Mapped[int] = mapped_column(Integer)
    crit_chance: Mapped[int] = mapped_column(Integer, default=0)
    crit_damage: Mapped[int] = mapped_column(Integer, default=100)
    dodge: Mapped[int] = mapped_column(Integer, default=0)
    hp_regeneration: Mapped[int] = mapped_column(Integer, default=0)

    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    spawned_at: Mapped[datetime] = mapped_column(DateTime)
    defeated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Discord message ID hosting the boss view (for edits)
    channel_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


class WorldBossParticipationModel(Base):
    __tablename__ = "world_boss_participations"
    __table_args__ = (
        UniqueConstraint("boss_id", "player_id", name="uq_world_boss_participation"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    boss_id: Mapped[int] = mapped_column(
        ForeignKey("world_bosses.id", ondelete="CASCADE"), index=True
    )
    player_id: Mapped[int] = mapped_column(
        ForeignKey("players.id", ondelete="CASCADE"), index=True
    )

    joined: Mapped[bool] = mapped_column(Boolean, default=True)
    damage_dealt: Mapped[int] = mapped_column(Integer, default=0)
    damage_tanked: Mapped[int] = mapped_column(Integer, default=0)
    hp_healed: Mapped[int] = mapped_column(Integer, default=0)
    fights_count: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
