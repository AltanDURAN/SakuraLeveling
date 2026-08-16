from datetime import datetime, UTC

from sqlalchemy import BigInteger, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.db.base import Base


class AdminCommandModel(Base):
    """File de commandes déposées par l'admin WEB et exécutées par le BOT.

    La webapp et le bot sont deux processus séparés : la webapp peut écrire en
    base (or, XP, items…) mais ne peut PAS parler à Discord. Pour les actions
    qui exigent le bot (faire spawner un monstre, un boss, un événement, couper
    un combat), l'admin dépose ici une commande `pending` ; le bot la ramasse
    (`AdminBridgeCog`, toutes les 5 s), l'exécute et écrit le résultat.

    Statuts : pending → done | failed. Les commandes restent en base comme
    journal d'audit (qui a fait quoi, quand, avec quel résultat).
    """

    __tablename__ = "admin_commands"

    id: Mapped[int] = mapped_column(primary_key=True)
    action: Mapped[str] = mapped_column(String(40), index=True)
    payload_json: Mapped[str] = mapped_column(Text, default="{}")

    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    result: Mapped[str] = mapped_column(Text, default="")

    requested_by: Mapped[int] = mapped_column(BigInteger, default=0)
    attempts: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), index=True
    )
    executed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
