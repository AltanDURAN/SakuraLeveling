"""Use cases de la brocante (marketplace P2P).

⚠️ ANTI-DUPLICATION ⚠️ : la brocante est sensible aux exploits classiques
(double-spend des items, gold infini par achat-revente race condition).
Les invariants à respecter :

1. Création d'annonce : `inventory.remove_item` AVANT le `marketplace.create`.
   Si l'inventaire ne suffit pas, refus immédiat. L'item est "en consigne"
   tant que l'annonce est active.

2. Achat : tout en une transaction logique :
       - Vérifier solde acheteur (refus si insuffisant)
       - Vérifier que le listing est encore ACTIVE (anti-race)
       - decrement gold acheteur
       - mark_sold (status passe à SOLD avant de donner les items, pour
         qu'un 2e click sur le même listing ne puisse pas le payer 2 fois)
       - inventory.add_item acheteur
       - increment gold vendeur (moins commission)

3. Annulation : tout en une transaction :
       - Vérifier que le listing appartient au vendeur
       - Vérifier qu'il est encore ACTIVE
       - mark_cancelled
       - inventory.add_item vendeur (restitution)

4. Expiration (cleanup loop) :
       - mark_expired bulk
       - Pour chaque listing expiré, restituer les items au vendeur

Commission : `MARKETPLACE_COMMISSION_PCT` (5% par défaut). Le shop garde
ce % du prix total — modèle de "frais de tenue de marché". Pas de cap.
"""

from dataclasses import dataclass, field
from datetime import datetime, UTC, timedelta

from app.domain.entities.marketplace_listing import (
    ListingStatus,
    MarketplaceListing,
)
from app.infrastructure.db.repositories.inventory_repository import InventoryRepository
from app.infrastructure.db.repositories.item_repository import ItemRepository
from app.infrastructure.db.repositories.marketplace_repository import (
    MarketplaceRepository,
)
from app.infrastructure.db.repositories.player_repository import PlayerRepository


MARKETPLACE_COMMISSION_PCT = 5  # 5% prélevé sur les ventes
MAX_LISTING_DAYS = 5  # durée par défaut d'une annonce
MAX_ACTIVE_LISTINGS_PER_PLAYER = 10  # limite anti-saturation


def _commission_amount(total: int) -> int:
    return int(total * MARKETPLACE_COMMISSION_PCT / 100)


# ---------- 1. List item ----------


@dataclass
class ListResult:
    success: bool
    message: str
    listing: MarketplaceListing | None = None


class ListItemForSaleUseCase:
    def __init__(
        self,
        player_repository: PlayerRepository,
        inventory_repository: InventoryRepository,
        item_repository: ItemRepository,
        marketplace_repository: MarketplaceRepository,
    ) -> None:
        self.player_repository = player_repository
        self.inventory_repository = inventory_repository
        self.item_repository = item_repository
        self.marketplace_repository = marketplace_repository

    def execute(
        self,
        seller_discord_id: int,
        seller_username: str,
        seller_display_name: str,
        item_code: str,
        quantity: int,
        price_per_unit: int,
        duration_days: int = MAX_LISTING_DAYS,
    ) -> ListResult:
        if quantity <= 0:
            return ListResult(False, "❌ La quantité doit être ≥ 1.")
        if price_per_unit <= 0:
            return ListResult(False, "❌ Le prix unitaire doit être ≥ 1.")
        if duration_days <= 0 or duration_days > MAX_LISTING_DAYS:
            return ListResult(
                False,
                f"❌ La durée doit être entre 1 et {MAX_LISTING_DAYS} jours.",
            )

        profile = self.player_repository.get_or_create_by_discord_id(
            discord_id=seller_discord_id,
            username=seller_username,
            display_name=seller_display_name,
        )

        # Limite anti-saturation
        active = self.marketplace_repository.list_active_for_seller(
            profile.player.id
        )
        if len(active) >= MAX_ACTIVE_LISTINGS_PER_PLAYER:
            return ListResult(
                False,
                f"❌ Limite atteinte : maximum {MAX_ACTIVE_LISTINGS_PER_PLAYER} "
                f"annonces actives en simultané.",
            )

        item = self.item_repository.get_by_code(item_code)
        if item is None:
            return ListResult(False, f"❌ Item `{item_code}` introuvable.")

        # Étape critique : retirer l'item de l'inventaire AVANT la création
        # de l'annonce. Si on inverse, un crash entre les 2 = item dupliqué.
        removed = self.inventory_repository.remove_item(
            player_id=profile.player.id,
            item_definition_id=item.id,
            quantity=quantity,
        )
        if not removed:
            return ListResult(
                False,
                f"❌ Vous n'avez pas {quantity}× **{item.name}** en inventaire.",
            )

        expires_at = datetime.now(UTC) + timedelta(days=duration_days)
        listing = self.marketplace_repository.create(
            seller_player_id=profile.player.id,
            item_definition_id=item.id,
            quantity=quantity,
            price_per_unit=price_per_unit,
            expires_at=expires_at,
        )

        return ListResult(
            success=True,
            message=(
                f"✅ Annonce créée : **{quantity}× {item.name}** à "
                f"**{price_per_unit}** or/u ({listing.total_price} or total). "
                f"Expire <t:{int(expires_at.timestamp())}:R>."
            ),
            listing=listing,
        )


# ---------- 2. Buy ----------


@dataclass
class BuyResult:
    success: bool
    message: str
    listing: MarketplaceListing | None = None
    total_paid: int = 0


class BuyMarketplaceListingUseCase:
    def __init__(
        self,
        player_repository: PlayerRepository,
        inventory_repository: InventoryRepository,
        marketplace_repository: MarketplaceRepository,
    ) -> None:
        self.player_repository = player_repository
        self.inventory_repository = inventory_repository
        self.marketplace_repository = marketplace_repository

    def execute(
        self,
        buyer_discord_id: int,
        buyer_username: str,
        buyer_display_name: str,
        listing_id: int,
    ) -> BuyResult:
        listing = self.marketplace_repository.get_by_id(listing_id)
        if listing is None:
            return BuyResult(False, "❌ Annonce introuvable.")
        if listing.status != ListingStatus.ACTIVE:
            return BuyResult(False, "❌ Annonce déjà clôturée.")

        # Pas de self-buy
        buyer_profile = self.player_repository.get_or_create_by_discord_id(
            discord_id=buyer_discord_id,
            username=buyer_username,
            display_name=buyer_display_name,
        )
        if buyer_profile.player.id == listing.seller_player_id:
            return BuyResult(False, "❌ Vous ne pouvez pas acheter votre propre annonce.")

        total_price = listing.total_price
        if buyer_profile.resources.gold < total_price:
            return BuyResult(
                False,
                f"❌ Fonds insuffisants : {total_price} or requis "
                f"(possédé : {buyer_profile.resources.gold}).",
            )

        # Étape critique anti-race :
        # 1. mark_sold AVANT de débiter le buyer (si 2 buyers cliquent en
        #    parallèle, le 2e verra status=SOLD et sera refusé)
        sold_listing = self.marketplace_repository.mark_sold(
            listing_id, buyer_profile.player.id
        )
        if sold_listing is None:
            return BuyResult(False, "❌ Erreur lors de la clôture de l'annonce.")

        # 2. Décrément buyer + crédit seller (avec commission)
        commission = _commission_amount(total_price)
        seller_payout = total_price - commission
        self.player_repository.add_gold(buyer_profile.player.id, -total_price)
        self.player_repository.add_gold(listing.seller_player_id, seller_payout)

        # 3. Donner les items au buyer
        self.inventory_repository.add_item(
            player_id=buyer_profile.player.id,
            item_definition_id=listing.item_definition_id,
            quantity=listing.quantity,
        )

        return BuyResult(
            success=True,
            message=(
                f"🛒 Achat conclu pour **{total_price}** or "
                f"(commission shop : {commission})."
            ),
            listing=sold_listing,
            total_paid=total_price,
        )


# ---------- 3. Cancel ----------


@dataclass
class CancelResult:
    success: bool
    message: str


class CancelMarketplaceListingUseCase:
    def __init__(
        self,
        player_repository: PlayerRepository,
        inventory_repository: InventoryRepository,
        marketplace_repository: MarketplaceRepository,
    ) -> None:
        self.player_repository = player_repository
        self.inventory_repository = inventory_repository
        self.marketplace_repository = marketplace_repository

    def execute(
        self,
        seller_discord_id: int,
        listing_id: int,
    ) -> CancelResult:
        listing = self.marketplace_repository.get_by_id(listing_id)
        if listing is None:
            return CancelResult(False, "❌ Annonce introuvable.")

        seller_profile = self.player_repository.get_by_discord_id(seller_discord_id)
        if seller_profile is None or seller_profile.player.id != listing.seller_player_id:
            return CancelResult(
                False, "❌ Cette annonce ne vous appartient pas."
            )
        if listing.status != ListingStatus.ACTIVE:
            return CancelResult(False, "❌ Annonce déjà clôturée.")

        # mark_cancelled AVANT la restitution des items pour anti-race
        self.marketplace_repository.mark_cancelled(listing_id)
        self.inventory_repository.add_item(
            player_id=listing.seller_player_id,
            item_definition_id=listing.item_definition_id,
            quantity=listing.quantity,
        )
        return CancelResult(
            success=True,
            message=f"✅ Annonce annulée. Items restitués à votre inventaire.",
        )


# ---------- 4. Expire (cleanup loop) ----------


@dataclass
class ExpireResult:
    expired_count: int
    items_returned: list = field(default_factory=list)  # list of (player_id, item_def_id, qty)


class ExpireMarketplaceListingsUseCase:
    """Marquage en bulk des listings dépassés + restitution des items.

    À appeler périodiquement par un loop côté bot. Idempotent : le 2e appel
    immédiat ne fait rien (toutes déjà expired).
    """

    def __init__(
        self,
        inventory_repository: InventoryRepository,
        marketplace_repository: MarketplaceRepository,
    ) -> None:
        self.inventory_repository = inventory_repository
        self.marketplace_repository = marketplace_repository

    def execute(self) -> ExpireResult:
        expired = self.marketplace_repository.expire_overdue()
        items_returned: list[tuple[int, int, int]] = []
        for listing in expired:
            self.inventory_repository.add_item(
                player_id=listing.seller_player_id,
                item_definition_id=listing.item_definition_id,
                quantity=listing.quantity,
            )
            items_returned.append(
                (listing.seller_player_id, listing.item_definition_id, listing.quantity)
            )
        return ExpireResult(
            expired_count=len(expired), items_returned=items_returned
        )
