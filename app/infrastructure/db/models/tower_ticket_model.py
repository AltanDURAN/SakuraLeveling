"""Tickets d'entrée de la tour solo (`/tour`).

Une ligne par joueur : le jour (UTC) et le nombre de tickets utilisés ce
jour-là. Les tickets ne s'accumulent pas : chaque jour on repart de son quota.
"""

from datetime import date

from sqlalchemy import Date, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.db.base import Base


class PlayerTowerTicketModel(Base):
    __tablename__ = "player_tower_tickets"

    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"), primary_key=True)
    day: Mapped[date] = mapped_column(Date)
    used: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
