"""Aventure commencée (tutoriel fini ou passé), par COMPTE Discord (08/11/2026).

Comme le règlement accepté : gardé à part du joueur, elle survit au reset d'un
joueur — le rôle Aventurier se rend ainsi à qui quitte le serveur puis
revient. Le reset de SAISON la vide : tout le monde repasse par le règlement
et le tutoriel (décision de l'auteur, 09/11/2026).
"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.db.base import Base


class AdventurerModel(Base):
    __tablename__ = "adventurers"

    discord_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    #: "termine" (tutoriel fini) ou "passe" (tutoriel passé).
    how: Mapped[str] = mapped_column(String(16), nullable=False, default="passe")
