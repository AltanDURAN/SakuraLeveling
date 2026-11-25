"""Porte d'entrée du serveur (25/11/2026, demande de l'auteur).

Une seule ligne (id = 1). Sans ligne : la porte est ouverte. Vidée au reset de
saison : une saison lancée rouvre la porte.
"""

from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.db.base import Base


class EntryGateModel(Base):
    __tablename__ = "entry_gate"

    id: Mapped[int] = mapped_column(primary_key=True)
    #: « ouverte », « testeurs » ou « fermee ».
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    #: Ouverture annoncée (UTC naïf), affichée à qui trouve la porte fermée.
    opens_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    changed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
