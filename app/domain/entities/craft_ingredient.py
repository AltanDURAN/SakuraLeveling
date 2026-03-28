from dataclasses import dataclass


@dataclass
class CraftIngredient:
    item_code: str
    quantity: int