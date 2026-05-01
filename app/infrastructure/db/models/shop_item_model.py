from datetime import datetime, UTC

from sqlalchemy import Boolean, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.db.base import Base


class ShopItemModel(Base):
    __tablename__ = "shop_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    item_definition_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("item_definitions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    buy_price: Mapped[int] = mapped_column(Integer, nullable=False)
    max_sell_price: Mapped[int] = mapped_column(Integer, nullable=False)
    min_sell_price: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    stock_threshold: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    current_stock: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))

    __table_args__ = (
        UniqueConstraint(
            "item_definition_id",
            name="uq_shop_items_item_definition_id",
        ),
    )
