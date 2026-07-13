from datetime import datetime, UTC

from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.db.base import Base


class PlayerElementEssenceModel(Base):
    """Essences élémentaires d'un joueur pour un élément donné (compteur).

    Une ligne par (joueur, élément). Les essences droppent en tuant des mobs de
    l'élément correspondant et sont AUTO-consommées pour monter l'affinité de ce
    même élément (coût N→N+1 = N+1 essences). Le compteur stocké = essences
    restantes après conversion (progression vers le palier suivant). Ressource
    dédiée : pas dans l'inventaire, pas échangeable.
    """

    __tablename__ = "player_element_essences"

    id: Mapped[int] = mapped_column(primary_key=True)
    player_id: Mapped[int] = mapped_column(
        ForeignKey("players.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    element: Mapped[str] = mapped_column(String(20), nullable=False)
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))

    __table_args__ = (
        UniqueConstraint("player_id", "element", name="uq_player_element_essence"),
    )
