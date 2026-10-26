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
    #: > 0 : prix = price_per_level × niveau du joueur (remplace buy_price) —
    #: pour un objet qui rapporte plus à haut niveau (parchemin d'oubli…).
    price_per_level: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    #: > 0 : on ne peut pas en posséder plus (achat refusé si on en a déjà).
    max_owned: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))

    __table_args__ = (
        UniqueConstraint(
            "item_definition_id",
            name="uq_shop_items_item_definition_id",
        ),
    )
