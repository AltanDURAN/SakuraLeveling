from dataclasses import dataclass

from app.domain.services.shop_pricing_service import ShopPricingService
from app.infrastructure.db.repositories.inventory_repository import InventoryRepository
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.repositories.shop_repository import ShopRepository


@dataclass
class BuyResult:
    success: bool
    message: str
    total_cost: int = 0
    item_name: str = ""
    quantity: int = 0


class BuyFromShopUseCase:
    """Achat shop→joueur : prix fixe `buy_price`, stock illimité côté shop.

    Le `current_stock` n'est pas affecté par l'achat — il représente la
    saturation du marché côté joueurs (uniquement modifié par les ventes).
    """

    def __init__(
        self,
        player_repository: PlayerRepository,
        inventory_repository: InventoryRepository,
        shop_repository: ShopRepository,
        shop_pricing_service: ShopPricingService,
    ) -> None:
        self.player_repository = player_repository
        self.inventory_repository = inventory_repository
        self.shop_repository = shop_repository
        self.shop_pricing_service = shop_pricing_service

    def execute(
        self,
        discord_id: int,
        username: str,
        display_name: str,
        item_code: str,
        quantity: int,
    ) -> BuyResult:
        if quantity <= 0:
            return BuyResult(success=False, message="La quantité doit être positive.")

        profile = self.player_repository.get_or_create_by_discord_id(
            discord_id=discord_id,
            username=username,
            display_name=display_name,
        )

        shop_item = self.shop_repository.get_by_item_code(item_code)
        if shop_item is None:
            return BuyResult(
                success=False,
                message=f"L'objet `{item_code}` n'est pas vendu au shop.",
            )

        if not shop_item.enabled:
            return BuyResult(
                success=False,
                message=f"`{shop_item.item_definition.name}` est actuellement indisponible à l'achat.",
            )

        total_cost = self.shop_pricing_service.total_buy_cost(shop_item, quantity)
        if profile.resources.gold < total_cost:
            return BuyResult(
                success=False,
                message=(
                    f"Fonds insuffisants : il vous manque "
                    f"**{total_cost - profile.resources.gold}** or "
                    f"(coût total {total_cost})."
                ),
            )

        self.player_repository.add_gold(profile.player.id, -total_cost)
        self.inventory_repository.add_item(
            player_id=profile.player.id,
            item_definition_id=shop_item.item_definition.id,
            quantity=quantity,
        )

        return BuyResult(
            success=True,
            message=(
                f"✅ Vous avez acheté **{quantity}× {shop_item.item_definition.name}** "
                f"pour **{total_cost}** or."
            ),
            total_cost=total_cost,
            item_name=shop_item.item_definition.name,
            quantity=quantity,
        )
