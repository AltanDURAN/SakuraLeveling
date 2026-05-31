"""Sets d'équipement nommés (loadouts) — un joueur peut sauvegarder
plusieurs configurations d'équipement et les rappeler via /equip_set.

Schéma :
- `player_equipment_sets` : un set = un nom unique par joueur + métadonnées
- `player_equipment_set_items` : 1 ligne par slot occupé du set,
  référence à un `ItemDefinition` (pas une instance d'inventaire — on
  stocke "quel type d'item équiper où" et on revérifie la possession
  au moment de l'équipement).
"""

from datetime import datetime, UTC

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.db.base import Base


class PlayerEquipmentSetModel(Base):
    __tablename__ = "player_equipment_sets"
    __table_args__ = (
        UniqueConstraint("player_id", "name", name="uq_player_set_name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    player_id: Mapped[int] = mapped_column(
        ForeignKey("players.id", ondelete="CASCADE"), index=True,
    )
    name: Mapped[str] = mapped_column(String(50))

    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))

    items = relationship(
        "PlayerEquipmentSetItemModel",
        cascade="all, delete-orphan",
        back_populates="equipment_set",
    )


class PlayerEquipmentSetItemModel(Base):
    __tablename__ = "player_equipment_set_items"
    __table_args__ = (
        UniqueConstraint(
            "equipment_set_id", "slot", name="uq_set_slot",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    equipment_set_id: Mapped[int] = mapped_column(
        ForeignKey("player_equipment_sets.id", ondelete="CASCADE"),
        index=True,
    )
    slot: Mapped[str] = mapped_column(String(50))
    item_definition_id: Mapped[int] = mapped_column(
        ForeignKey("item_definitions.id"), index=True,
    )

    equipment_set = relationship(
        "PlayerEquipmentSetModel", back_populates="items",
    )
    item_definition = relationship("ItemDefinitionModel")
