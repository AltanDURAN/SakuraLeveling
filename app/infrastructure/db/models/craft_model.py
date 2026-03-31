from datetime import datetime, UTC

from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.db.base import Base


class CraftRecipeModel(Base):
    __tablename__ = "craft_recipes"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(100))

    result_item_definition_id: Mapped[int] = mapped_column(
        ForeignKey("item_definitions.id"),
        index=True,
    )
    result_quantity: Mapped[int] = mapped_column(Integer, default=1)

    created_at: Mapped[datetime] = mapped_column(default=datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(default=datetime.now(UTC))


class CraftRecipeIngredientModel(Base):
    __tablename__ = "craft_recipe_ingredients"
    __table_args__ = (
        UniqueConstraint("craft_recipe_id", "item_definition_id", name="uq_craft_ingredient"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    craft_recipe_id: Mapped[int] = mapped_column(
        ForeignKey("craft_recipes.id"),
        index=True,
    )
    item_definition_id: Mapped[int] = mapped_column(
        ForeignKey("item_definitions.id"),
        index=True,
    )
    quantity: Mapped[int] = mapped_column(Integer)