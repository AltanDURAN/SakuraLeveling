from app.domain.entities.shop_item import ShopItem


class ShopPricingService:
    """Calcule les prix dynamiques d'un objet en shop.

    Le prix d'achat (buy_price) est fixe, défini par l'admin.
    Le prix de vente (ce que le joueur reçoit en vendant au shop) varie
    linéairement entre `max_sell_price` (stock vide) et `min_sell_price`
    (stock ≥ stock_threshold). Au-delà du seuil, le prix reste à min.
    """

    def current_sell_price(self, shop_item: ShopItem) -> int:
        if shop_item.stock_threshold <= 0:
            return shop_item.max_sell_price

        ratio = min(1.0, max(0.0, shop_item.current_stock / shop_item.stock_threshold))
        delta = shop_item.max_sell_price - shop_item.min_sell_price
        price = shop_item.max_sell_price - ratio * delta
        return max(shop_item.min_sell_price, round(price))

    def total_buy_cost(self, shop_item: ShopItem, quantity: int) -> int:
        if quantity <= 0:
            return 0
        return shop_item.buy_price * quantity

    def total_sell_amount(self, shop_item: ShopItem, quantity: int) -> int:
        """Total versé au joueur pour `quantity` objets vendus.

        On simule la dégradation au fur et à mesure de la vente : chaque unité
        est vendue à son prix calculé après l'ajout des unités précédentes au
        stock. Cela évite l'exploit consistant à vendre 1000 objets d'un coup
        au prix maximal.
        """
        if quantity <= 0:
            return 0

        total = 0
        simulated_stock = shop_item.current_stock

        for _ in range(quantity):
            simulated_item = ShopItem(
                id=shop_item.id,
                item_definition=shop_item.item_definition,
                buy_price=shop_item.buy_price,
                max_sell_price=shop_item.max_sell_price,
                min_sell_price=shop_item.min_sell_price,
                stock_threshold=shop_item.stock_threshold,
                current_stock=simulated_stock,
                enabled=shop_item.enabled,
                created_at=shop_item.created_at,
                updated_at=shop_item.updated_at,
            )
            total += self.current_sell_price(simulated_item)
            simulated_stock += 1

        return total
