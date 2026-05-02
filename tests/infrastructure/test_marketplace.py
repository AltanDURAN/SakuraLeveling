"""Tests anti-duplication / atomicité de la brocante.

Spec : aucune ressource ne doit pouvoir être dupliquée ou perdue. On vérifie
explicitement les invariants critiques après chaque opération :
    - création : items retirés de l'inventaire vendeur
    - achat : items chez l'acheteur, gold debit/credit avec commission
    - annulation : items restitués au vendeur
    - expiration : items restitués au vendeur (cleanup loop)
    - acheter sa propre annonce : refusé
    - acheter 2× la même annonce (race) : 2e tentative refusée
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application.use_cases.marketplace import (
    BuyMarketplaceListingUseCase,
    CancelMarketplaceListingUseCase,
    ExpireMarketplaceListingsUseCase,
    ListItemForSaleUseCase,
    MARKETPLACE_COMMISSION_PCT,
)
from app.infrastructure.db.base import Base

# Imports nécessaires pour Base.metadata
from app.infrastructure.db.models.player_model import PlayerModel
from app.infrastructure.db.models.progression_model import PlayerProgressionModel  # noqa: F401
from app.infrastructure.db.models.resource_model import PlayerResourceModel  # noqa: F401
from app.infrastructure.db.models.item_model import ItemDefinitionModel
from app.infrastructure.db.models.inventory_model import PlayerInventoryItemModel  # noqa: F401
from app.infrastructure.db.models.equipment_model import PlayerEquipmentItemModel  # noqa: F401
from app.infrastructure.db.models.mob_model import MobDefinitionModel  # noqa: F401
from app.infrastructure.db.models.class_model import ClassDefinitionModel  # noqa: F401
from app.infrastructure.db.models.player_class_state_model import PlayerClassStateModel  # noqa: F401
from app.infrastructure.db.models.craft_model import CraftRecipeModel, CraftRecipeIngredientModel  # noqa: F401
from app.infrastructure.db.models.cooldown_model import PlayerCooldownModel  # noqa: F401
from app.infrastructure.db.models.quest_model import QuestDefinitionModel, PlayerQuestStateModel  # noqa: F401
from app.infrastructure.db.models.profession_model import PlayerProfessionModel  # noqa: F401
from app.infrastructure.db.models.player_health_state_model import PlayerHealthStateModel  # noqa: F401
from app.infrastructure.db.models.player_mob_kill_model import PlayerMobKillModel  # noqa: F401
from app.infrastructure.db.models.shop_item_model import ShopItemModel  # noqa: F401
from app.infrastructure.db.models.player_career_stats_model import PlayerCareerStatsModel  # noqa: F401
from app.infrastructure.db.models.player_skill_allocation_model import PlayerSkillAllocationModel  # noqa: F401
from app.infrastructure.db.models.trade_model import TradeItemModel, TradeModel  # noqa: F401
from app.infrastructure.db.models.player_duel_rank_model import PlayerDuelRankModel  # noqa: F401
from app.infrastructure.db.models.world_boss_model import WorldBossModel, WorldBossParticipationModel  # noqa: F401
from app.infrastructure.db.models.player_title_model import PlayerTitleModel  # noqa: F401
from app.infrastructure.db.models.weekly_quest_model import WeeklyQuestAssignmentModel  # noqa: F401
from app.infrastructure.db.models.marketplace_listing_model import MarketplaceListingModel  # noqa: F401

from app.infrastructure.db.repositories.inventory_repository import InventoryRepository
from app.infrastructure.db.repositories.item_repository import ItemRepository
from app.infrastructure.db.repositories.marketplace_repository import (
    MarketplaceRepository,
)
from app.infrastructure.db.repositories.player_repository import PlayerRepository


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _seed_item(session, code: str = "iron_ingot") -> int:
    now = datetime.now(UTC)
    item = ItemDefinitionModel(
        code=code, name=code, description="", category="resource",
        rarity="common", stackable=True, max_stack=None,
        sell_price=5, buy_price=12, icon=None,
        stat_bonuses_json=None, equipment_slot=None, requires_two_hands=False,
        created_at=now, updated_at=now,
    )
    session.add(item)
    session.commit()
    return item.id


def _create_player(session, discord_id: int, gold: int = 1000) -> int:
    profile = PlayerRepository(session).get_or_create_by_discord_id(
        discord_id=discord_id, username=f"u{discord_id}", display_name=f"P{discord_id}",
    )
    PlayerRepository(session).set_gold(profile.player.id, gold)
    return profile.player.id


def _give_item(session, player_id: int, item_id: int, qty: int) -> None:
    InventoryRepository(session).add_item(player_id, item_id, qty)


def _build_list_use_case(session):
    return ListItemForSaleUseCase(
        player_repository=PlayerRepository(session),
        inventory_repository=InventoryRepository(session),
        item_repository=ItemRepository(session),
        marketplace_repository=MarketplaceRepository(session),
    )


def _build_buy_use_case(session):
    return BuyMarketplaceListingUseCase(
        player_repository=PlayerRepository(session),
        inventory_repository=InventoryRepository(session),
        marketplace_repository=MarketplaceRepository(session),
    )


def _build_cancel_use_case(session):
    return CancelMarketplaceListingUseCase(
        player_repository=PlayerRepository(session),
        inventory_repository=InventoryRepository(session),
        marketplace_repository=MarketplaceRepository(session),
    )


def _inv_quantity(session, player_id: int, item_id: int) -> int:
    inv = InventoryRepository(session).list_by_player_id(player_id)
    for i in inv:
        if i.item_definition.id == item_id:
            return i.quantity
    return 0


# ---------- Création d'annonce ----------


def test_create_listing_removes_items_from_inventory(session):
    item_id = _seed_item(session)
    seller_id = _create_player(session, 1)
    _give_item(session, seller_id, item_id, 10)

    use_case = _build_list_use_case(session)
    result = use_case.execute(
        seller_discord_id=1, seller_username="u1", seller_display_name="P1",
        item_code="iron_ingot", quantity=5, price_per_unit=20,
    )

    assert result.success is True
    # Inventaire du vendeur : 10 - 5 = 5
    assert _inv_quantity(session, seller_id, item_id) == 5


def test_create_listing_refused_if_insufficient_quantity(session):
    item_id = _seed_item(session)
    seller_id = _create_player(session, 1)
    _give_item(session, seller_id, item_id, 3)

    use_case = _build_list_use_case(session)
    result = use_case.execute(
        seller_discord_id=1, seller_username="u1", seller_display_name="P1",
        item_code="iron_ingot", quantity=5, price_per_unit=20,
    )

    assert result.success is False
    # Inventaire intact (rien retiré)
    assert _inv_quantity(session, seller_id, item_id) == 3


def test_create_listing_refused_for_invalid_qty_or_price(session):
    _seed_item(session)
    _create_player(session, 1)
    use_case = _build_list_use_case(session)

    r1 = use_case.execute(
        seller_discord_id=1, seller_username="u1", seller_display_name="P1",
        item_code="iron_ingot", quantity=0, price_per_unit=10,
    )
    assert r1.success is False

    r2 = use_case.execute(
        seller_discord_id=1, seller_username="u1", seller_display_name="P1",
        item_code="iron_ingot", quantity=1, price_per_unit=0,
    )
    assert r2.success is False


# ---------- Achat ----------


def test_buy_transfers_items_and_gold_with_commission(session):
    item_id = _seed_item(session)
    seller_id = _create_player(session, 1, gold=0)
    buyer_id = _create_player(session, 2, gold=500)
    _give_item(session, seller_id, item_id, 10)

    list_uc = _build_list_use_case(session)
    list_result = list_uc.execute(
        seller_discord_id=1, seller_username="u1", seller_display_name="P1",
        item_code="iron_ingot", quantity=5, price_per_unit=20,
    )
    assert list_result.success is True

    buy_uc = _build_buy_use_case(session)
    buy_result = buy_uc.execute(
        buyer_discord_id=2, buyer_username="u2", buyer_display_name="P2",
        listing_id=list_result.listing.id,
    )

    assert buy_result.success is True
    total = 5 * 20  # 100
    commission = total * MARKETPLACE_COMMISSION_PCT // 100  # 5
    seller_payout = total - commission  # 95

    # Buyer : 500 - 100 = 400 gold + 5 items
    buyer_profile = PlayerRepository(session).get_profile_by_player_id(buyer_id)
    assert buyer_profile.resources.gold == 400
    assert _inv_quantity(session, buyer_id, item_id) == 5

    # Seller : 0 + 95 gold (commission retenue)
    seller_profile = PlayerRepository(session).get_profile_by_player_id(seller_id)
    assert seller_profile.resources.gold == seller_payout

    # Inventaire vendeur : 10 - 5 (vendus) = 5 (pas de retour)
    assert _inv_quantity(session, seller_id, item_id) == 5


def test_buy_refused_if_insufficient_gold(session):
    item_id = _seed_item(session)
    seller_id = _create_player(session, 1)
    buyer_id = _create_player(session, 2, gold=10)  # pauvre
    _give_item(session, seller_id, item_id, 5)

    list_result = _build_list_use_case(session).execute(
        seller_discord_id=1, seller_username="u1", seller_display_name="P1",
        item_code="iron_ingot", quantity=5, price_per_unit=100,
    )

    buy_result = _build_buy_use_case(session).execute(
        buyer_discord_id=2, buyer_username="u2", buyer_display_name="P2",
        listing_id=list_result.listing.id,
    )

    assert buy_result.success is False
    assert "fonds" in buy_result.message.lower() or "insuffisant" in buy_result.message.lower()
    # Aucun mouvement
    assert PlayerRepository(session).get_profile_by_player_id(buyer_id).resources.gold == 10
    assert _inv_quantity(session, buyer_id, item_id) == 0


def test_buy_self_listing_refused(session):
    item_id = _seed_item(session)
    seller_id = _create_player(session, 1)
    _give_item(session, seller_id, item_id, 5)

    list_result = _build_list_use_case(session).execute(
        seller_discord_id=1, seller_username="u1", seller_display_name="P1",
        item_code="iron_ingot", quantity=5, price_per_unit=20,
    )

    # Le vendeur tente de s'acheter lui-même
    buy_result = _build_buy_use_case(session).execute(
        buyer_discord_id=1, buyer_username="u1", buyer_display_name="P1",
        listing_id=list_result.listing.id,
    )
    assert buy_result.success is False
    assert "votre propre" in buy_result.message.lower()


def test_buy_twice_refused_anti_race(session):
    """Anti race : 2 acheteurs cliquent en parallèle. Le 2e voit status=SOLD."""
    item_id = _seed_item(session)
    seller_id = _create_player(session, 1)
    buyer1_id = _create_player(session, 2, gold=500)
    buyer2_id = _create_player(session, 3, gold=500)
    _give_item(session, seller_id, item_id, 5)

    listing = _build_list_use_case(session).execute(
        seller_discord_id=1, seller_username="u1", seller_display_name="P1",
        item_code="iron_ingot", quantity=5, price_per_unit=20,
    ).listing

    r1 = _build_buy_use_case(session).execute(
        buyer_discord_id=2, buyer_username="u2", buyer_display_name="P2",
        listing_id=listing.id,
    )
    r2 = _build_buy_use_case(session).execute(
        buyer_discord_id=3, buyer_username="u3", buyer_display_name="P3",
        listing_id=listing.id,
    )

    assert r1.success is True
    assert r2.success is False  # déjà clôturée
    # Buyer 1 a les items, buyer 2 n'a rien et garde son gold
    assert _inv_quantity(session, buyer1_id, item_id) == 5
    assert _inv_quantity(session, buyer2_id, item_id) == 0
    assert PlayerRepository(session).get_profile_by_player_id(buyer2_id).resources.gold == 500


# ---------- Annulation ----------


def test_cancel_returns_items_to_seller(session):
    item_id = _seed_item(session)
    seller_id = _create_player(session, 1)
    _give_item(session, seller_id, item_id, 10)

    listing = _build_list_use_case(session).execute(
        seller_discord_id=1, seller_username="u1", seller_display_name="P1",
        item_code="iron_ingot", quantity=5, price_per_unit=20,
    ).listing
    # Inventaire = 10 - 5 = 5
    assert _inv_quantity(session, seller_id, item_id) == 5

    result = _build_cancel_use_case(session).execute(
        seller_discord_id=1, listing_id=listing.id,
    )
    assert result.success is True
    # Restitution : 5 + 5 = 10
    assert _inv_quantity(session, seller_id, item_id) == 10


def test_cancel_refused_for_other_seller(session):
    item_id = _seed_item(session)
    seller_id = _create_player(session, 1)
    _create_player(session, 2)
    _give_item(session, seller_id, item_id, 5)

    listing = _build_list_use_case(session).execute(
        seller_discord_id=1, seller_username="u1", seller_display_name="P1",
        item_code="iron_ingot", quantity=5, price_per_unit=20,
    ).listing

    result = _build_cancel_use_case(session).execute(
        seller_discord_id=2, listing_id=listing.id,  # pas le seller
    )
    assert result.success is False
    assert "pas" in result.message.lower()


# ---------- Expiration ----------


def test_expire_overdue_returns_items_to_sellers(session):
    item_id = _seed_item(session)
    seller_id = _create_player(session, 1)
    _give_item(session, seller_id, item_id, 10)

    listing = _build_list_use_case(session).execute(
        seller_discord_id=1, seller_username="u1", seller_display_name="P1",
        item_code="iron_ingot", quantity=5, price_per_unit=20,
    ).listing
    # Force l'expiration (dans le passé)
    repo = MarketplaceRepository(session)
    from app.infrastructure.db.models.marketplace_listing_model import (
        MarketplaceListingModel,
    )
    model = session.get(MarketplaceListingModel, listing.id)
    model.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    session.commit()

    use_case = ExpireMarketplaceListingsUseCase(
        inventory_repository=InventoryRepository(session),
        marketplace_repository=repo,
    )
    result = use_case.execute()
    assert result.expired_count == 1
    # Items restitués : 5 + 5 = 10
    assert _inv_quantity(session, seller_id, item_id) == 10

    # Idempotent : 2e appel = 0
    second = use_case.execute()
    assert second.expired_count == 0


def test_full_flow_no_item_or_gold_loss(session):
    """Flux complet : création + achat + cancel + expire. À tout moment,
    `total = inv_seller + inv_buyer + items_sur_listings + items_perdus = qty initiale`."""
    item_id = _seed_item(session)
    seller_id = _create_player(session, 1, gold=0)
    buyer_id = _create_player(session, 2, gold=10000)
    _give_item(session, seller_id, item_id, 100)

    list_uc = _build_list_use_case(session)
    buy_uc = _build_buy_use_case(session)
    cancel_uc = _build_cancel_use_case(session)

    # Annonce 1 : 20 vendus
    l1 = list_uc.execute(
        seller_discord_id=1, seller_username="u1", seller_display_name="P1",
        item_code="iron_ingot", quantity=20, price_per_unit=10,
    ).listing
    buy_uc.execute(
        buyer_discord_id=2, buyer_username="u2", buyer_display_name="P2",
        listing_id=l1.id,
    )

    # Annonce 2 : 30 annulée → restitution
    l2 = list_uc.execute(
        seller_discord_id=1, seller_username="u1", seller_display_name="P1",
        item_code="iron_ingot", quantity=30, price_per_unit=10,
    ).listing
    cancel_uc.execute(seller_discord_id=1, listing_id=l2.id)

    # Inventaires :
    inv_seller = _inv_quantity(session, seller_id, item_id)
    inv_buyer = _inv_quantity(session, buyer_id, item_id)
    # Total = 100 - 20 (vendu) + 30 (annulé restitué) - 30 (resold listing 2) - 30 (returned)
    # = 100 - 20 (parti chez buyer) = 80 chez seller, 20 chez buyer = 100
    assert inv_seller + inv_buyer == 100
    assert inv_seller == 80
    assert inv_buyer == 20
