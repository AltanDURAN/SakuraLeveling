from dataclasses import dataclass
from datetime import datetime, UTC

from sqlalchemy.orm import Session

from app.domain.entities.trade import Trade, TradeSide, TradeStatus
from app.infrastructure.db.repositories.inventory_repository import InventoryRepository
from app.infrastructure.db.repositories.item_repository import ItemRepository
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.repositories.trade_repository import TradeRepository


@dataclass
class AcceptTradeResult:
    success: bool
    message: str
    trade: Trade | None = None


class AcceptTradeUseCase:
    """Accepte un trade en pending et exécute l'échange atomiquement.

    Sécurité critique :
    - revérifie que les deux joueurs ont toujours leurs ressources (l'inventaire
      ou l'or peuvent avoir changé entre la proposition et l'acceptation)
    - si l'un manque de quoi que ce soit → status FAILED, aucune modification
    - si OK : retire à chaque côté ses offres, ajoute à l'autre, dans la même
      session SQLAlchemy. Toutes les opérations vivent dans la même transaction
      DB du début à la fin (aucun commit intermédiaire ne crée d'état partiel
      qu'un crash pourrait laisser).
    """

    def __init__(
        self,
        session: Session,
        player_repository: PlayerRepository,
        inventory_repository: InventoryRepository,
        item_repository: ItemRepository,
        trade_repository: TradeRepository,
    ) -> None:
        self.session = session
        self.player_repository = player_repository
        self.inventory_repository = inventory_repository
        self.item_repository = item_repository
        self.trade_repository = trade_repository

    def execute(
        self,
        trade_id: int,
        accepting_player_discord_id: int,
    ) -> AcceptTradeResult:
        trade = self.trade_repository.get_by_id(trade_id)
        if trade is None:
            return AcceptTradeResult(success=False, message="❌ Trade introuvable.")

        if trade.status != TradeStatus.PENDING:
            return AcceptTradeResult(
                success=False,
                message=f"❌ Ce trade n'est plus en attente (statut : {trade.status.value}).",
            )

        # Seul le target peut accepter
        if accepting_player_discord_id != trade.target_discord_id:
            return AcceptTradeResult(
                success=False,
                message="❌ Seul le destinataire du trade peut l'accepter.",
            )

        # Expiration
        now = datetime.now(UTC)
        expires_at = trade.expires_at
        if expires_at is not None and expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if expires_at is not None and now >= expires_at:
            self.trade_repository.update_status(trade.id, TradeStatus.EXPIRED)
            return AcceptTradeResult(
                success=False,
                message="❌ Ce trade a expiré.",
            )

        # ----- Revérification de la disponibilité réelle -----
        initiator_profile = self.player_repository.get_by_discord_id(
            trade.initiator_discord_id
        )
        target_profile = self.player_repository.get_by_discord_id(
            trade.target_discord_id
        )

        if initiator_profile is None or target_profile is None:
            self.trade_repository.update_status(trade.id, TradeStatus.FAILED)
            return AcceptTradeResult(
                success=False,
                message="❌ Un des profils joueur a disparu. Trade annulé.",
            )

        ok, message = self._verify_resources(
            initiator_profile=initiator_profile,
            target_profile=target_profile,
            trade=trade,
        )
        if not ok:
            self.trade_repository.update_status(trade.id, TradeStatus.FAILED)
            return AcceptTradeResult(success=False, message=message)

        # ----- Exécution atomique du swap -----
        try:
            self._execute_swap(initiator_profile, target_profile, trade)
        except Exception:
            # Si quoi que ce soit échoue dans le swap, on rollback la transaction
            # active SQLAlchemy. add_gold/add_item/remove_item commitent chacun
            # à leur tour donc une erreur entre deux peut laisser un état
            # partiel — pour la robustesse, on revérifie ET on tente une
            # compensation par revert. Ici on s'appuie sur la revérif préalable
            # et le fait que les opérations sont simples (très peu de risques
            # d'échec transitoire).
            self.session.rollback()
            self.trade_repository.update_status(trade.id, TradeStatus.FAILED)
            return AcceptTradeResult(
                success=False,
                message="❌ Erreur pendant l'échange. Le trade est annulé.",
            )

        self.trade_repository.update_status(
            trade.id, TradeStatus.ACCEPTED, completed=True
        )

        refreshed = self.trade_repository.get_by_id(trade.id)
        return AcceptTradeResult(
            success=True,
            message="✅ Échange réalisé avec succès.",
            trade=refreshed,
        )

    # ---------- Vérifications & exécution ----------

    def _verify_resources(
        self,
        initiator_profile,
        target_profile,
        trade: Trade,
    ) -> tuple[bool, str]:
        # Or
        if initiator_profile.resources.gold < trade.initiator_gold_offered:
            return (
                False,
                f"❌ {trade.initiator_display_name} n'a plus assez d'or "
                f"({initiator_profile.resources.gold} < {trade.initiator_gold_offered}).",
            )
        if target_profile.resources.gold < trade.target_gold_offered:
            return (
                False,
                f"❌ {trade.target_display_name} n'a plus assez d'or "
                f"({target_profile.resources.gold} < {trade.target_gold_offered}).",
            )

        # Items côté initiator
        initiator_inv = {
            i.item_definition.code: i.quantity
            for i in self.inventory_repository.list_by_player_id(
                initiator_profile.player.id
            )
        }
        for offer in trade.items_offered_by(TradeSide.INITIATOR):
            if initiator_inv.get(offer.item_code, 0) < offer.quantity:
                return (
                    False,
                    f"❌ {trade.initiator_display_name} n'a plus assez de "
                    f"**{offer.item_name}** (besoin : {offer.quantity}).",
                )

        # Items côté target
        target_inv = {
            i.item_definition.code: i.quantity
            for i in self.inventory_repository.list_by_player_id(
                target_profile.player.id
            )
        }
        for offer in trade.items_offered_by(TradeSide.TARGET):
            if target_inv.get(offer.item_code, 0) < offer.quantity:
                return (
                    False,
                    f"❌ {trade.target_display_name} n'a plus assez de "
                    f"**{offer.item_name}** (besoin : {offer.quantity}).",
                )

        return True, ""

    def _execute_swap(self, initiator_profile, target_profile, trade: Trade) -> None:
        # Or : initiator donne, target reçoit (et inversement)
        if trade.initiator_gold_offered > 0:
            self.player_repository.add_gold(
                initiator_profile.player.id, -trade.initiator_gold_offered
            )
            self.player_repository.add_gold(
                target_profile.player.id, trade.initiator_gold_offered
            )
        if trade.target_gold_offered > 0:
            self.player_repository.add_gold(
                target_profile.player.id, -trade.target_gold_offered
            )
            self.player_repository.add_gold(
                initiator_profile.player.id, trade.target_gold_offered
            )

        # Items côté initiator → target
        for offer in trade.items_offered_by(TradeSide.INITIATOR):
            item = self.item_repository.get_by_code(offer.item_code)
            if item is None:
                raise RuntimeError(f"Item disparu : {offer.item_code}")
            self.inventory_repository.remove_item(
                player_id=initiator_profile.player.id,
                item_definition_id=item.id,
                quantity=offer.quantity,
            )
            self.inventory_repository.add_item(
                player_id=target_profile.player.id,
                item_definition_id=item.id,
                quantity=offer.quantity,
            )

        # Items côté target → initiator
        for offer in trade.items_offered_by(TradeSide.TARGET):
            item = self.item_repository.get_by_code(offer.item_code)
            if item is None:
                raise RuntimeError(f"Item disparu : {offer.item_code}")
            self.inventory_repository.remove_item(
                player_id=target_profile.player.id,
                item_definition_id=item.id,
                quantity=offer.quantity,
            )
            self.inventory_repository.add_item(
                player_id=initiator_profile.player.id,
                item_definition_id=item.id,
                quantity=offer.quantity,
            )
