"""Parchemin d'oubli et jeton d'arbre ne passent pas d'un joueur à l'autre
(décision de l'auteur, 14/11/2026) : leur prix suit le niveau de l'acheteur,
un compte de niveau 1 les achetait pour un compte de niveau 80."""

from app.application.use_cases.create_trade import CreateTradeUseCase, TradeOffer
from app.application.use_cases.marketplace import ListItemForSaleUseCase
from app.domain.services.merchant_items import UNTRADEABLE, is_tradeable
from app.infrastructure.db.repositories.gear_repository import GearRepository
from app.infrastructure.db.repositories.inventory_repository import InventoryRepository
from app.infrastructure.db.repositories.item_repository import ItemRepository
from app.infrastructure.db.repositories.marketplace_repository import MarketplaceRepository
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.repositories.trade_repository import TradeRepository
from tests.infrastructure.test_use_consumable import session  # noqa: F401


def test_les_objets_a_prix_indexe_existent_et_sont_verrouilles():
    import json
    from pathlib import Path

    shop = json.loads(Path("app/infrastructure/content/shop_items.json").read_text(encoding="utf-8"))
    rows = shop["items"] if isinstance(shop, dict) else shop
    per_level = {r.get("item_code") or r.get("code") for r in rows if r.get("price_per_level")}
    assert per_level and per_level <= UNTRADEABLE          # tout objet au prix indexé est verrouillé
    assert is_tradeable("potion_soin") and not is_tradeable("parchemin_oubli")


def _build(cls, session):
    import inspect

    repos = {"player_repository": PlayerRepository(session), "inventory_repository": InventoryRepository(session),
             "item_repository": ItemRepository(session), "marketplace_repository": MarketplaceRepository(session),
             "trade_repository": TradeRepository(session), "gear_repository": GearRepository(session)}
    wanted = [p for p in inspect.signature(cls.__init__).parameters if p != "self"]
    return cls(**{name: repos[name] for name in wanted if name in repos})


def test_ni_echange_ni_brocante(session):
    PlayerRepository(session).get_or_create_by_discord_id(1, "a", "A")
    PlayerRepository(session).get_or_create_by_discord_id(2, "b", "B")
    for code in sorted(UNTRADEABLE):
        sale = _build(ListItemForSaleUseCase, session).execute(1, "a", "A", code, 1, 100)
        assert not sale.success and "ne se vendent pas" in sale.message
        trade = _build(CreateTradeUseCase, session).execute(
            1, 2, "a", "A", "B", TradeOffer(items=[(code, 1)], gold=0), TradeOffer(items=[], gold=10))
        assert not trade.success and "ne s'échangent pas" in trade.message
        asked = _build(CreateTradeUseCase, session).execute(
            1, 2, "a", "A", "B", TradeOffer(items=[], gold=10), TradeOffer(items=[(code, 1)], gold=0))
        assert not asked.success                       # ni proposé, ni demandé
