from dataclasses import dataclass
from datetime import datetime

from app.domain.entities.craft_ingredient import CraftIngredient


@dataclass
class CraftRecipe:
    id: int
    code: str
    name: str
    result_item_code: str
    result_quantity: int
    ingredients: list[CraftIngredient]
    created_at: datetime
    updated_at: datetime