from datetime import datetime

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.db.base import Base


class PlayerEquipmentItemModel(Base):
    __tablename__ = "player_equipment"
    __table_args__ = (
        UniqueConstraint("player_id", "slot", name="uq_player_equipment_slot"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"), index=True)
    slot: Mapped[str] = mapped_column(String(50))
    item_definition_id: Mapped[int] = mapped_column(
        ForeignKey("item_definitions.id"),
        index=True,
    )

    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)

    item_definition = relationship("ItemDefinitionModel")