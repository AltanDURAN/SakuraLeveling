from dataclasses import dataclass
from datetime import datetime


@dataclass
class ItemDefinition:
    id: int
    code: str
    name: str
    description: str
    category: str
    rarity: str
    stackable: bool
    max_stack: int | None
    sell_price: int
    buy_price: int | None
    icon: str | None
    created_at: datetime
    updated_at: datetime