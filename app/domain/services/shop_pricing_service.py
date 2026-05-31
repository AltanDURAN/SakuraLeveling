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
