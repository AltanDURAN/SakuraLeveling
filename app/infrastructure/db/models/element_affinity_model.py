from datetime import datetime, UTC

from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.db.base import Base


class PlayerElementAffinityModel(Base):
    """Affinité élémentaire d'un joueur pour un élément donné (0..100).

    Une ligne par (joueur, élément). Tirée aléatoirement à la création du
    profil, améliorable plus tard via un item d'affinité.
    """

    __tablename__ = "player_element_affinities"

    id: Mapped[int] = mapped_column(primary_key=True)
    player_id: Mapped[int] = mapped_column(
        ForeignKey("players.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    element: Mapped[str] = mapped_column(String(20), nullable=False)
    value: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))

    __table_args__ = (
        UniqueConstraint("player_id", "element", name="uq_player_element"),
    )
