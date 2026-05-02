from dataclasses import dataclass, field
from datetime import datetime, UTC

from app.domain.entities.trade import Trade, TradeSide
from app.infrastructure.db.repositories.inventory_repository import InventoryRepository
from app.infrastructure.db.repositories.item_repository import ItemRepository
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.repositories.trade_repository import TradeRepository


@dataclass
class TradeOffer:
    """Format d'entrée des items proposés par un côté du trade."""

    items: list[tuple[str, int]] = field(default_factory=list)  # (item_code, quantity)
    gold: int = 0


@dataclass
class CreateTradeResult:
    success: bool
    message: str
    trade: Trade | None = None


class CreateTradeUseCase:
    """Crée un trade en pending, après validation que :
    - les deux joueurs existent
    - initiator ≠ target
    - au moins un côté propose quelque chose
    - les items proposés par l'initiator existent et sont dans son inventaire
    - les items demandés (proposés par le target) existent en définition
      (la dispo chez le target est revérifiée à l'acceptation)
    - les quantités sont positives
    - l'initiator n'a pas un trade pending déjà actif avec la cible
    """

    def __init__(
        self,
        player_repository: PlayerRepository,
        inventory_repository: InventoryRepository,
        item_repository: ItemRepository,
        trade_repository: TradeRepository,
    ) -> None:
        self.player_repository = player_repository
        self.inventory_repository = inventory_repository
        self.item_repository = item_repository
        self.trade_repository = trade_repository

    def execute(
        self,
        initiator_discord_id: int,
        target_discord_id: int,
        initiator_username: str,
        initiator_display_name: str,
        target_display_name: str,
        initiator_offer: TradeOffer,
        target_request: TradeOffer,
        ttl_minutes: int = 5,
    ) -> CreateTradeResult:
        if initiator_discord_id == target_discord_id:
            return CreateTradeResult(
                success=False,
                message="❌ Vous ne pouvez pas commercer avec vous-même.",
            )

        # Validation des quantités positives
        for side_offer, side_label in (
            (initiator_offer, "votre offre"),
            (target_request, "la demande"),
        ):
            if side_offer.gold < 0:
                return CreateTradeResult(
                    success=False,
                    message=f"❌ L'or proposé dans {side_label} doit être ≥ 0.",
                )
            for item_code, quantity in side_offer.items:
                if quantity <= 0:
                    return CreateTradeResult(
                        success=False,
                        message=f"❌ Quantité invalide pour `{item_code}` dans {side_label}.",
                    )

        # Au moins un côté doit proposer quelque chose
        nothing_offered = (
            not initiator_offer.items
            and initiator_offer.gold == 0
            and not target_request.items
            and target_request.gold == 0
        )
        if nothing_offered:
            return CreateTradeResult(
                success=False,
                message="❌ Le trade est vide : proposez ou demandez au moins quelque chose.",
            )

        initiator_profile = self.player_repository.get_or_create_by_discord_id(
            discord_id=initiator_discord_id,
            username=initiator_username,
            display_name=initiator_display_name,
        )
        target_profile = self.player_repository.get_by_discord_id(target_discord_id)

        if target_profile is None:
            return CreateTradeResult(
                success=False,
                message=f"❌ {target_display_name} n'a pas encore de profil joueur.",
            )

        # Vérifie qu'on n'a pas déjà un trade pending entre ces deux joueurs
        existing = self.trade_repository.list_pending_for_pair(
            initiator_profile.player.id, target_profile.player.id
        )
        # Filtre les expirés (au cas où le job de cleanup ne soit pas passé)
        now = datetime.now(UTC)

        def _is_active(trade) -> bool:
            expires = trade.expires_at or now
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=UTC)
            return expires > now

        active = [t for t in existing if _is_active(t)]
        if active:
            return CreateTradeResult(
                success=False,
                message=(
                    "❌ Un trade pending existe déjà entre vous deux. "
                    "Annulez-le ou attendez son expiration."
                ),
            )

        # Validation des items : existence + dispo chez l'initiator
        initiator_inventory = self.inventory_repository.list_by_player_id(
            initiator_profile.player.id
        )
        inventory_by_code = {
            i.item_definition.code: i.quantity for i in initiator_inventory
        }

        # Total par item (gère les doublons dans le formulaire)
        initiator_offer_totals = _aggregate_quantities(initiator_offer.items)
        target_request_totals = _aggregate_quantities(target_request.items)

        # Or de l'initiator suffisant
        if initiator_profile.resources.gold < initiator_offer.gold:
            return CreateTradeResult(
                success=False,
                message=(
                    f"❌ Vous n'avez que **{initiator_profile.resources.gold}** or, "
                    f"impossible d'en proposer **{initiator_offer.gold}**."
                ),
            )

        # Items de l'initiator présents et en quantité suffisante
        for item_code, qty in initiator_offer_totals.items():
            item = self.item_repository.get_by_code(item_code)
            if item is None:
                return CreateTradeResult(
                    success=False,
                    message=f"❌ Item proposé inconnu : `{item_code}`.",
                )
            available = inventory_by_code.get(item_code, 0)
            if available < qty:
                return CreateTradeResult(
                    success=False,
                    message=(
                        f"❌ Vous n'avez pas assez de **{item.name}** "
                        f"(possédé : {available}, proposé : {qty})."
                    ),
                )

        # Items demandés au target : existence en définition
        # La dispo chez le target est revérifiée à l'acceptation pour gérer
        # le cas où ses ressources changent entre proposition et accept.
        for item_code, qty in target_request_totals.items():
            item = self.item_repository.get_by_code(item_code)
            if item is None:
                return CreateTradeResult(
                    success=False,
                    message=f"❌ Item demandé inconnu : `{item_code}`.",
                )

        # Construction de la liste pour le repository
        items_payload = []
        for item_code, qty in initiator_offer_totals.items():
            item = self.item_repository.get_by_code(item_code)
            items_payload.append((TradeSide.INITIATOR, item.id, qty))
        for item_code, qty in target_request_totals.items():
            item = self.item_repository.get_by_code(item_code)
            items_payload.append((TradeSide.TARGET, item.id, qty))

        trade = self.trade_repository.create_pending(
            initiator_player_id=initiator_profile.player.id,
            target_player_id=target_profile.player.id,
            initiator_gold_offered=initiator_offer.gold,
            target_gold_offered=target_request.gold,
            items=items_payload,
            ttl_minutes=ttl_minutes,
        )

        return CreateTradeResult(
            success=True,
            message="✅ Proposition de trade créée.",
            trade=trade,
        )


def _aggregate_quantities(items: list[tuple[str, int]]) -> dict[str, int]:
    """Permet à l'utilisateur de répéter le même item code, on additionne."""
    totals: dict[str, int] = {}
    for code, qty in items:
        totals[code] = totals.get(code, 0) + qty
    return totals
