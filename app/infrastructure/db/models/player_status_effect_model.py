from datetime import datetime, UTC

from sqlalchemy import DateTime, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.db.base import Base


class PlayerStatusEffectModel(Base):
    """Effet temporaire (buff/debuff) sur un joueur.

    V1 : un seul `kind` = "all_stats_pct" — `multiplier` s'applique à TOUTES
    les stats de combat positives (1.10 = buff +10%, 0.5 = debuff ÷2). Plusieurs
    effets actifs se cumulent multiplicativement. `expires_at` borne la durée ;
    les effets expirés sont ignorés à la lecture et purgés périodiquement.
    """

    __tablename__ = "player_status_effects"

    id: Mapped[int] = mapped_column(primary_key=True)
    player_id: Mapped[int] = mapped_column(
        ForeignKey("players.id", ondelete="CASCADE"), index=True
    )
    code: Mapped[str] = mapped_column(String(50))
    kind: Mapped[str] = mapped_column(String(30), default="all_stats_pct")
    multiplier: Mapped[float] = mapped_column(Float, default=1.0)

    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC)
    )
