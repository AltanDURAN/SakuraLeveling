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

    #: Rang gagné aux épreuves (F → SSS). Le rôle Discord ouvre les salons ;
    #: ce champ le garde si le joueur quitte le serveur et revient.
    earned_rank: Mapped[str] = mapped_column(String(4), default="F", server_default="F")
    # Tactique de combat (/tactique) : cible du sort de soin, figée en combat.
    combat_tactic: Mapped[str] = mapped_column(String(20), default="egoiste", server_default="egoiste")
    #: Type de bonus de panoplie choisi (`/panoplie`) — cf. set_bonus_service.
    panoplie_bonus: Mapped[str] = mapped_column(String(20), default="attack", server_default="attack")

    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
    last_seen_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))

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