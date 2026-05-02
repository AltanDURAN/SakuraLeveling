from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class TradeStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"  # accepté + complété
    REFUSED = "refused"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    FAILED = "failed"  # ressources manquantes au moment de l'acceptation


class TradeSide(StrEnum):
    INITIATOR = "initiator"
    TARGET = "target"


@dataclass
class TradeItemOffer:
    item_code: str
    item_name: str
    quantity: int
    offered_by: TradeSide


@dataclass
class Trade:
    id: int
    initiator_player_id: int
    initiator_discord_id: int
    initiator_display_name: str
    target_player_id: int
    target_discord_id: int
    target_display_name: str
    status: TradeStatus
    initiator_gold_offered: int
    target_gold_offered: int
    items: list[TradeItemOffer] = field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None
    expires_at: datetime | None = None
    completed_at: datetime | None = None

    @property
    def is_pending(self) -> bool:
        return self.status == TradeStatus.PENDING

    def items_offered_by(self, side: TradeSide) -> list[TradeItemOffer]:
        return [item for item in self.items if item.offered_by == side]

    def gold_offered_by(self, side: TradeSide) -> int:
        if side == TradeSide.INITIATOR:
            return self.initiator_gold_offered
        return self.target_gold_offered
