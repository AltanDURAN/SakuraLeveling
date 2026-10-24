"""Maîtrise relationnelle des artisans, par joueur.

(Les commandes de fabrication — `player_work_orders` — ont disparu avec la
fabrication : équipement v2, les artisans fusionnent. Migration 7d2b9e4f1a63.)
"""

from datetime import datetime, UTC

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.db.base import Base


class PlayerArtisanMasteryModel(Base):
    """Maîtrise d'un artisan VIS-À-VIS d'un joueur.

    Elle ne mesure pas le talent du PNJ dans l'absolu mais la relation de
    travail : ce qu'il a déjà fabriqué pour ce joueur précis. Deux joueurs
    voient donc le même personnage à des paliers différents.
    """

    __tablename__ = "player_artisan_mastery"
    __table_args__ = (
        UniqueConstraint("player_id", "artisan_code", name="uq_player_artisan"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    player_id: Mapped[int] = mapped_column(
        ForeignKey("players.id", ondelete="CASCADE"), index=True
    )
    artisan_code: Mapped[str] = mapped_column(String(40), index=True)
    orders_completed: Mapped[int] = mapped_column(Integer, default=0)
    gold_spent: Mapped[int] = mapped_column(Integer, default=0)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC)
    )
