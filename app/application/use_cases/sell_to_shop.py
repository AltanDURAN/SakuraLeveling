from dataclasses import dataclass

from app.domain.services.shop_pricing_service import ShopPricingService
from app.infrastructure.db.repositories.inventory_repository import InventoryRepository
from app.infrastructure.db.repositories.item_repository import ItemRepository
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.repositories.shop_repository import ShopRepository


@dataclass
class SellResult:
    success: bool
    message: str
    total_gain: int = 0
    item_name: str = ""
    quantity: int = 0


class SellToShopUseCase:
    """Vente joueur→shop : prix dynamique selon la saturation du marché.

    Le total versé tient compte de la dégradation progressive : chaque unité
    vendue augmente le stock simulé pour l'unité suivante. Cela évite l'exploit
    de vendre 1000 unités d'un coup au prix max.
    """

    def __init__(
        self,
        player_repository: PlayerRepository,
        inventory_repository: InventoryRepository,
        item_repository: ItemRepository,
        shop_repository: ShopRepository,
        shop_pricing_service: ShopPricingService,
    ) -> None:
        self.player_repository = player_repository
        self.inventory_repository = inventory_repository
        self.item_repository = item_repository
        self.shop_repository = shop_repository
        self.shop_pricing_service = shop_pricing_service

    def execute(
        self,
        discord_id: int,
        username: str,
        display_name: str,
        item_code: str,
        quantity: int,
    ) -> SellResult:
        if quantity <= 0:
            return SellResult(success=False, message="La quantité doit être positive.")

        profile = self.player_repository.get_or_create_by_discord_id(
            discord_id=discord_id,
            username=username,
            display_name=display_name,
        )

        shop_item = self.shop_repository.get_by_item_code(item_code)
        if shop_item is None:
            return SellResult(
                success=False,
                message=f"Le shop n'achète pas l'objet `{item_code}`.",
            )

        if not shop_item.enabled:
            return SellResult(
                success=False,
                message=f"Le shop n'achète pas actuellement de **{shop_item.item_definition.name}**.",
            )

        item = self.item_repository.get_by_code(item_code)
        if item is None:
            return SellResult(
                success=False,
                message=f"Définition d'objet `{item_code}` introuvable.",
            )

        total_gain = self.shop_pricing_service.total_sell_amount(shop_item, quantity)

        removed = self.inventory_repository.remove_item(
            player_id=profile.player.id,
            item_definition_id=item.id,
            quantity=quantity,
        )
        if not removed:
            return SellResult(
                success=False,
                message=(
                    f"Vous n'avez pas {quantity}× **{shop_item.item_definition.name}** "
                    "dans votre inventaire."
                ),
            )

        self.shop_repository.add_to_stock(shop_item.id, quantity)
        self.player_repository.add_gold(profile.player.id, total_gain)

        return SellResult(
            success=True,
            message=(
                f"✅ Vous avez vendu **{quantity}× {shop_item.item_definition.name}** "
                f"pour **{total_gain}** or."
            ),
            total_gain=total_gain,
            item_name=shop_item.item_definition.name,
            quantity=quantity,
        )
