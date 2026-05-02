"""Entité d'une annonce de brocante (marketplace P2P).

Une annonce active = stock retiré de l'inventaire vendeur, en attente d'acheteur.
À l'expiration ou annulation : items rendus au vendeur (et None gold).
À la vente : items donnés à l'acheteur, gold (moins commission) au vendeur.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class ListingStatus(str, Enum):
    ACTIVE = "active"
    SOLD = "sold"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


@dataclass
class MarketplaceListing:
    id: int
    seller_player_id: int
    item_definition_id: int
    quantity: int
    price_per_unit: int
    status: ListingStatus
    listed_at: datetime
    expires_at: datetime
    closed_at: datetime | None
    last_buyer_player_id: int | None

    @property
    def total_price(self) -> int:
        return self.quantity * self.price_per_unit
