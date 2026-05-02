from datetime import datetime, UTC

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.db.base import Base


class TradeModel(Base):
    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(primary_key=True)
    initiator_player_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("players.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    target_player_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("players.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="pending",
        index=True,
    )
    initiator_gold_offered: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    target_gold_offered: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )

    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class TradeItemModel(Base):
    __tablename__ = "trade_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    trade_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("trades.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    offered_by: Mapped[str] = mapped_column(String(20), nullable=False)
    item_definition_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("item_definitions.id", ondelete="CASCADE"),
        nullable=False,
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)

    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
