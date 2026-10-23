"""Échange et brocante d'une pièce d'équipement : on cède un EXEMPLAIRE précis."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application.use_cases.accept_trade import AcceptTradeUseCase
from app.application.use_cases.create_trade import CreateTradeUseCase, TradeOffer
from app.application.use_cases.marketplace import (
    BuyMarketplaceListingUseCase,
    CancelMarketplaceListingUseCase,
    ExpireMarketplaceListingsUseCase,
    ListItemForSaleUseCase,
)
from app.domain.services.gear_service import gear_ref
from app.infrastructure.db.base import Base
from app.infrastructure.db.models.item_model import ItemDefinitionModel
from app.infrastructure.db.models.marketplace_listing_model import MarketplaceListingModel
from app.infrastructure.db.models.resource_model import PlayerResourceModel
from app.infrastructure.db.repositories.gear_repository import GearRepository
from app.infrastructure.db.repositories.inventory_repository import InventoryRepository
from app.infrastructure.db.repositories.item_repository import ItemRepository
from app.infrastructure.db.repositories.marketplace_repository import MarketplaceRepository
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.repositories.trade_repository import TradeRepository

NOW = datetime.now(UTC)


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


@pytest.fixture()
def world(session):
    sword = ItemDefinitionModel(
        code="surin_dentele", name="Surin dentelé", description="", category="arme",
        rarity="common", stackable=False, max_stack=None, sell_price=0, buy_price=None,
        icon=None, stat_bonuses_json={"attack_pct": 8}, equipment_slot="arme",
        requires_two_hands=False, family="", created_at=NOW, updated_at=NOW,
    )
    session.add(sword)
    session.commit()
    players = PlayerRepository(session)
    alice = players.get_or_create_by_discord_id(1, "alice", "Alice").player.id
    bob = players.get_or_create_by_discord_id(2, "bob", "Bob").player.id
    for pid in (alice, bob):
        session.get(PlayerResourceModel, pid).gold = 10_000
    session.commit()
    epic = GearRepository(session).add(alice, sword.id, "epic", forge_level=3)
    return alice, bob, epic


def _gold(session, pid):
    session.expire_all()
    return session.get(PlayerResourceModel, pid).gold


def _market(session):
    repos = dict(player_repository=PlayerRepository(session),
                 inventory_repository=InventoryRepository(session),
                 marketplace_repository=MarketplaceRepository(session))
    return (
        ListItemForSaleUseCase(item_repository=ItemRepository(session), **repos),
        BuyMarketplaceListingUseCase(**repos),
        CancelMarketplaceListingUseCase(**repos),
    )


def _list(session, epic, price=500):
    sell, _, _ = _market(session)
    return sell.execute(1, "alice", "Alice", gear_ref(epic.id), 1, price)


# ------------------------------------------------------------- brocante --
def test_une_piece_en_vente_est_consignee(session, world):
    alice, _, epic = world
    res = _list(session, epic)
    assert res.success and res.listing.gear_id == epic.id and res.listing.quantity == 1
    gear = GearRepository(session)
    assert gear.get(epic.id).listed
    assert gear.list_owned(alice) == []          # ni portée, ni fusionnée, ni échangée
    assert not _list(session, epic).success      # pas deux annonces


def test_achat_transfere_l_exemplaire(session, world):
    alice, bob, epic = world
    listing = _list(session, epic).listing
    _, buy, _ = _market(session)
    res = buy.execute(2, "bob", "Bob", listing.id)
    assert res.success
    owned = GearRepository(session).list_owned(bob)
    assert [(g.id, g.rarity, g.forge_level) for g in owned] == [(epic.id, "epic", 3)]
    assert _gold(session, bob) == 9_500 and _gold(session, alice) == 10_000 + 475


def test_annulation_et_expiration_rendent_la_piece(session, world):
    alice, _, epic = world
    listing = _list(session, epic).listing
    _, _, cancel = _market(session)
    assert cancel.execute(1, listing.id).success
    assert [g.id for g in GearRepository(session).list_owned(alice)] == [epic.id]

    listing = _list(session, epic).listing
    session.get(MarketplaceListingModel, listing.id).expires_at = NOW - timedelta(days=1)
    session.commit()
    ExpireMarketplaceListingsUseCase(InventoryRepository(session),
                                     MarketplaceRepository(session)).execute()
    assert [g.id for g in GearRepository(session).list_owned(alice)] == [epic.id]


def test_on_ne_vend_pas_une_piece_portee(session, world):
    _, _, epic = world
    GearRepository(session).set_slot(epic.id, "arme_1")
    res = _list(session, epic)
    assert not res.success and "Retire" in res.message


# ------------------------------------------------------------- échanges --
def _trade(session, offer=(), request=()):
    uc = CreateTradeUseCase(PlayerRepository(session), InventoryRepository(session),
                            ItemRepository(session), TradeRepository(session))
    return uc.execute(1, 2, "alice", "Alice", "Bob",
                      TradeOffer(items=list(offer)), TradeOffer(items=list(request), gold=300))


def _accept(session, trade_id):
    return AcceptTradeUseCase(session, PlayerRepository(session), InventoryRepository(session),
                              ItemRepository(session), TradeRepository(session)).execute(trade_id, 2)


def test_echange_d_une_piece(session, world):
    alice, bob, epic = world
    created = _trade(session, offer=[(gear_ref(epic.id), 1), (gear_ref(epic.id), 1)])
    assert created.success
    offers = created.trade.items
    assert len(offers) == 1 and offers[0].gear_id == epic.id and offers[0].rarity == "epic"
    assert _accept(session, created.trade.id).success
    assert [g.id for g in GearRepository(session).list_owned(bob)] == [epic.id]
    assert _gold(session, alice) == 10_300


def test_on_ne_propose_pas_une_piece_portee_ni_en_vente(session, world):
    _, _, epic = world
    gear = GearRepository(session)
    gear.set_slot(epic.id, "arme_1")
    assert not _trade(session, offer=[(gear_ref(epic.id), 1)]).success
    gear.set_slot(epic.id, None)
    _list(session, epic)
    assert not _trade(session, offer=[(gear_ref(epic.id), 1)]).success


def test_piece_vendue_entre_proposition_et_acceptation(session, world):
    _, _, epic = world
    created = _trade(session, offer=[(gear_ref(epic.id), 1)])
    _list(session, epic)
    res = _accept(session, created.trade.id)
    assert not res.success and "n'a plus" in res.message


def test_demander_la_piece_portee_de_l_autre(session, world):
    alice, bob, epic = world
    # Bob demande… c'est Alice l'initiatrice : elle réclame la pièce de Bob.
    GearRepository(session).transfer(epic.id, bob)
    GearRepository(session).set_slot(epic.id, "arme_1")
    created = _trade(session, request=[(gear_ref(epic.id), 1)])
    assert created.success
    assert _accept(session, created.trade.id).success
    moved = GearRepository(session).get(epic.id)
    assert moved.player_id == alice and not moved.equipped
