from datetime import datetime, UTC

from sqlalchemy import DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.db.base import Base


class HelpSubscriberModel(Base):
    """Joueurs ayant accepté d'être tagués lors d'un appel à l'aide depuis
    le bouton 'Demander de l'aide' d'un encounter (système /chad).
    """

    __tablename__ = "help_subscribers"

    id: Mapped[int] = mapped_column(primary_key=True)
    player_id: Mapped[int] = mapped_column(
        ForeignKey("players.id", ondelete="CASCADE"),
        unique=True,
    )
    subscribed_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC)
    )
