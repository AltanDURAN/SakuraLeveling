from datetime import datetime, UTC

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.db.base import Base


class PlayerCosmeticModel(Base):
    """Cosmétiques PORTÉS sur la bannière `/profil` (un par emplacement).

    Les cosmétiques possédés sont des objets d'inventaire (catégorie
    `cosmetic`, achetés chez Sorn) ; ici, seulement le choix du joueur
    (`/apparence`). Un code vide = l'apparence par défaut.
    """

    __tablename__ = "player_cosmetics"

    player_id: Mapped[int] = mapped_column(
        ForeignKey("players.id", ondelete="CASCADE"), primary_key=True
    )
    fond: Mapped[str | None] = mapped_column(String(60), nullable=True)
    cadre: Mapped[str | None] = mapped_column(String(60), nullable=True)
    titre: Mapped[str | None] = mapped_column(String(60), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC)
    )
