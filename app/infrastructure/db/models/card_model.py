"""Cartes à collectionner : ce que l'inventaire ne dit pas.

Les cartes elles-mêmes sont des objets d'inventaire (catégorie `carte`) ;
cette ligne par joueur garde ses pétales (recyclage des doublons), le
compteur de la pitié, le booster offert et le moment où son album a grandi
(départage du record « album le plus complet »).
"""

from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.db.base import Base


class PlayerCardStateModel(Base):
    __tablename__ = "player_card_states"

    player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), primary_key=True)
    petals: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    boosters_opened: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    #: Boosters ouverts depuis le dernier légendaire ou mythique (pitié).
    since_top: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    free_booster_used: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    #: Cartes différentes au dernier agrandissement de l'album, et quand.
    album_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    album_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
