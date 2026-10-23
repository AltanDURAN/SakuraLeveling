from datetime import datetime, UTC

from sqlalchemy import ForeignKey, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.db.base import Base


class PlayerGearModel(Base):
    """Une pièce d'équipement POSSÉDÉE — un exemplaire précis.

    Les pièces ne sont plus fongibles : chaque copie a sa rareté, son niveau de
    forge sacrée et peut s'échanger seule (un mythique est unique). Une pièce
    PORTÉE a son `equipped_slot` renseigné ; l'index unique partiel garantit
    qu'un emplacement ne porte jamais deux pièces, même sur deux clics
    simultanés.
    """

    __tablename__ = "player_gear"
    __table_args__ = (
        Index(
            "uq_player_gear_equipped_slot", "player_id", "equipped_slot",
            unique=True, sqlite_where=text("equipped_slot IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    player_id: Mapped[int] = mapped_column(
        ForeignKey("players.id", ondelete="CASCADE"), index=True,
    )
    item_definition_id: Mapped[int] = mapped_column(
        ForeignKey("item_definitions.id", ondelete="CASCADE"), index=True,
    )
    rarity: Mapped[str] = mapped_column(String(16), nullable=False, default="common")
    forge_level: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    equipped_slot: Mapped[str | None] = mapped_column(String(50), nullable=True)
    #: drop | fusion | trade | admin — pour l'historique et l'admin.
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="drop", server_default="drop")

    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))

    item_definition = relationship("ItemDefinitionModel")
