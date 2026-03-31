from datetime import datetime, UTC

from sqlalchemy import Boolean, Integer, String, JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.db.base import Base


class ItemDefinitionModel(Base):
    __tablename__ = "item_definitions"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(String(255), default="")
    category: Mapped[str] = mapped_column(String(50))
    rarity: Mapped[str] = mapped_column(String(50), default="common")
    stackable: Mapped[bool] = mapped_column(Boolean, default=True)
    max_stack: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sell_price: Mapped[int] = mapped_column(Integer, default=0)
    buy_price: Mapped[int | None] = mapped_column(Integer, nullable=True)
    icon: Mapped[str | None] = mapped_column(String(255), nullable=True)
    stat_bonuses_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(default=datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(default=datetime.now(UTC))