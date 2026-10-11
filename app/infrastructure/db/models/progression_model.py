from datetime import datetime, UTC

from sqlalchemy import ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.db.base import Base


class PlayerProgressionModel(Base):
    __tablename__ = "player_progressions"

    player_id: Mapped[int] = mapped_column(
        ForeignKey("players.id"), primary_key=True
    )

    level: Mapped[int] = mapped_column(Integer, default=1)
    xp: Mapped[int] = mapped_column(Integer, default=0)
    skill_points: Mapped[int] = mapped_column(Integer, default=0)
    #: Points de stats NON dépensés (1 par niveau).
    stat_points: Mapped[int] = mapped_column(Integer, default=0)
    #: Répartition déjà effectuée — on stocke les POINTS, pas les stats,
    #: pour pouvoir retoucher la valeur d'un point sans migration.
    points_attack: Mapped[int] = mapped_column(Integer, default=0)
    points_defense: Mapped[int] = mapped_column(Integer, default=0)
    points_max_hp: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))

    player = relationship("PlayerModel", back_populates="progression")