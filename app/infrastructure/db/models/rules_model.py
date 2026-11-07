"""Règlement accepté, par COMPTE Discord (07/11/2026).

Gardé à part du joueur : on accepte avant d'avoir un personnage, et
l'acceptation survit au reset d'un joueur comme au reset de saison.
"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.db.base import Base


class RulesAcceptanceModel(Base):
    __tablename__ = "rules_acceptances"

    discord_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    #: Dernière version du règlement acceptée.
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    accepted_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
