from datetime import datetime, UTC

from sqlalchemy import ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.db.base import Base


class PlayerInventoryItemModel(Base):
    __tablename__ = "player_inventory_items"
    __table_args__ = (
        UniqueConstraint("player_id", "item_definition_id", name="uq_player_item"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"), index=True)
    item_definition_id: Mapped[int] = mapped_column(
        ForeignKey("item_definitions.id"),
        index=True,
    )
    quantity: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(default=datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(default=datetime.now(UTC))

    item_definition = relationship("ItemDefinitionModel")