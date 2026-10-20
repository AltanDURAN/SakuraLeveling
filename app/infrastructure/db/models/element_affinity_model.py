from datetime import datetime, UTC

from sqlalchemy import Boolean, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.db.base import Base


class PlayerElementAffinityModel(Base):
    """Affinité élémentaire d'un joueur pour un élément donné.

    Une ligne par (joueur, élément). L'affinité part de 0 et monte avec les
    essences ; son rythme dépend du TALENT, tiré à la création du personnage
    (cf. element_talent_service). `talent` NULL = pas encore tiré.
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
    talent: Mapped[int | None] = mapped_column(Integer, nullable=True)
    affinity_cap: Mapped[int] = mapped_column(Integer, nullable=False, default=100, server_default="100")
    revealed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")

    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))

    __table_args__ = (
        UniqueConstraint("player_id", "element", name="uq_player_element"),
    )
