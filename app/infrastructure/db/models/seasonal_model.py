"""Événements saisonniers (calendrier de l'Avent, Noël, boutiques
d'événement — décembre 2026).

  • `seasonal_claims` : ce qu'un joueur a déjà pris (une case de l'Avent, le
    cadeau de Noël…), une ligne par (joueur, événement, clé) ;
  • `event_shop_purchases` : ce qu'il a acheté dans une boutique
    d'événement (limite par joueur) ;
  • `seasonal_announcements` : les annonces déjà postées (une seule fois,
    même après un redémarrage) et le panneau épinglé du salon des événements.
"""

from datetime import UTC, datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.db.base import Base


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class SeasonalClaimModel(Base):
    __tablename__ = "seasonal_claims"
    __table_args__ = (UniqueConstraint("player_id", "event_code", "claim_key", name="uq_seasonal_claim"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), index=True)
    #: « advent », « christmas »…
    event_code: Mapped[str] = mapped_column(String(40))
    #: La case (« 2026-12-05 ») ou « gift ».
    claim_key: Mapped[str] = mapped_column(String(40))
    claimed_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    payload_json: Mapped[str] = mapped_column(Text, default="{}")


class EventShopPurchaseModel(Base):
    __tablename__ = "event_shop_purchases"

    player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), primary_key=True)
    shop_code: Mapped[str] = mapped_column(String(40), primary_key=True)
    item_code: Mapped[str] = mapped_column(String(80), primary_key=True)
    quantity: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class SeasonalAnnouncementModel(Base):
    __tablename__ = "seasonal_announcements"

    #: « advent:2026-12-01 », « new_year:2027-01-01 »… ou « panel ».
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    posted_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
