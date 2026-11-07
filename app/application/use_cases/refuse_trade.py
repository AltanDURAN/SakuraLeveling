from dataclasses import dataclass

from app.domain.entities.trade import Trade, TradeStatus
from app.infrastructure.db.repositories.trade_repository import TradeRepository


@dataclass
class RefuseTradeResult:
    success: bool
    message: str
    trade: Trade | None = None


class RefuseTradeUseCase:
    """Le destinataire refuse un trade pending."""

    def __init__(self, trade_repository: TradeRepository) -> None:
        self.trade_repository = trade_repository

    def execute(
        self, trade_id: int, refusing_player_discord_id: int
    ) -> RefuseTradeResult:
        trade = self.trade_repository.get_by_id(trade_id)
        if trade is None:
            return RefuseTradeResult(success=False, message="❌ Échange introuvable.")

        if trade.status != TradeStatus.PENDING:
            return RefuseTradeResult(
                success=False,
                message="❌ Cet échange n'est plus en attente.",
            )

        if refusing_player_discord_id != trade.target_discord_id:
            return RefuseTradeResult(
                success=False,
                message="❌ Seul le destinataire de l'échange peut le refuser.",
            )

        self.trade_repository.update_status(trade.id, TradeStatus.REFUSED)
        return RefuseTradeResult(
            success=True,
            message="✋ Échange refusé.",
            trade=self.trade_repository.get_by_id(trade.id),
        )


@dataclass
class CancelTradeResult:
    success: bool
    message: str
    trade: Trade | None = None


class CancelTradeUseCase:
    """L'initiator annule son propre trade pending."""

    def __init__(self, trade_repository: TradeRepository) -> None:
        self.trade_repository = trade_repository

    def execute(
        self, trade_id: int, cancelling_player_discord_id: int
    ) -> CancelTradeResult:
        trade = self.trade_repository.get_by_id(trade_id)
        if trade is None:
            return CancelTradeResult(success=False, message="❌ Échange introuvable.")

        if trade.status != TradeStatus.PENDING:
            return CancelTradeResult(
                success=False,
                message="❌ Cet échange n'est plus en attente.",
            )

        if cancelling_player_discord_id != trade.initiator_discord_id:
            return CancelTradeResult(
                success=False,
                message="❌ Seul l'auteur de l'échange peut l'annuler.",
            )

        self.trade_repository.update_status(trade.id, TradeStatus.CANCELLED)
        return CancelTradeResult(
            success=True,
            message="🛑 Échange annulé.",
            trade=self.trade_repository.get_by_id(trade.id),
        )
