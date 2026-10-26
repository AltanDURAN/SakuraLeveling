from dataclasses import dataclass
from datetime import datetime

from app.domain.entities.item_definition import ItemDefinition


@dataclass
class ShopItem:
    id: int
    item_definition: ItemDefinition
    buy_price: int
    max_sell_price: int
    min_sell_price: int
    stock_threshold: int
    current_stock: int
    enabled: bool
    created_at: datetime
    updated_at: datetime
    #: > 0 : prix = price_per_level × niveau du joueur (au lieu de buy_price).
    price_per_level: int = 0
    #: > 0 : quantité maximale possédée (achat refusé au-delà).
    max_owned: int = 0
