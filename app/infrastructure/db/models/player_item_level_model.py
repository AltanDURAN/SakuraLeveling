from datetime import datetime, UTC

from sqlalchemy import DateTime, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.db.base import Base


class PlayerItemLevelModel(Base):
    """Niveau de forge d'un équipement pour un joueur (« forge sacrée »).

    L'inventaire/équipement étant FONGIBLE (pas d'instances, quantité par
    définition), le niveau est stocké par (joueur, item_definition). Chaque
    niveau ajoute les stats de base de l'item une fois de plus (cap défini par
    l'événement, défaut 10). Survit au déséquipement/rééquipement.
    """

    __tablename__ = "player_item_levels"
    __table_args__ = (
        UniqueConstraint("player_id", "item_definition_id", name="uq_player_item_level"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    player_id: Mapped[int] = mapped_column(
        ForeignKey("players.id", ondelete="CASCADE"), index=True
    )
    item_definition_id: Mapped[int] = mapped_column(
        ForeignKey("item_definitions.id", ondelete="CASCADE"), index=True
    )
    level: Mapped[int] = mapped_column(Integer, default=0)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC)
    )
