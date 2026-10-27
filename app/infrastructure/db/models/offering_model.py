"""Offrande commune : la jauge du serveur (une seule ligne, id = 1) et les
dons de chaque joueur pour la jauge en cours (`cycle`)."""

from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.db.base import Base


class OfferingStateModel(Base):
    __tablename__ = "offering_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cycle: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    target: Mapped[int] = mapped_column(Integer, default=1_500, server_default="1500")
    contributed: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    fills: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    filled_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    #: Dernier jour où le prix a été mis à jour (baisse des jours sans remplissage).
    priced_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    deity_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    blessed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    blessing_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    filled_by: Mapped[int | None] = mapped_column(Integer, nullable=True)


class OfferingContributionModel(Base):
    __tablename__ = "offering_contributions"

    cycle: Mapped[int] = mapped_column(Integer, primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), primary_key=True)
    amount: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
