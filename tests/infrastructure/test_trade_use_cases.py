"""Tests des use cases de trade : Create, Accept, Refuse, Cancel.

Sécurité critique : on vérifie que ni duplication ni perte d'item ne peut
survenir, et que les ressources sont revérifiées à l'acceptation (pas
seulement à la proposition).
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application.use_cases.accept_trade import AcceptTradeUseCase
from app.application.use_cases.create_trade import (
    CreateTradeUseCase,
    TradeOffer,
)
from app.application.use_cases.refuse_trade import (
    CancelTradeUseCase,
    RefuseTradeUseCase,
)
from app.domain.entities.trade import TradeStatus
from app.infrastructure.db.base import Base

# Tous les modèles pour Base.metadata
from app.infrastructure.db.models.player_model import PlayerModel
from app.infrastructure.db.models.progression_model import PlayerProgressionModel  # noqa: F401
from app.infrastructure.db.models.resource_model import PlayerResourceModel
from app.infrastructure.db.models.item_model import ItemDefinitionModel
from app.infrastructure.db.models.inventory_model import PlayerInventoryItemModel
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

from app.infrastructure.db.repositories.inventory_repository import InventoryRepository
from app.infrastructure.db.repositories.item_repository import ItemRepository
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.repositories.trade_repository import TradeRepository


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


def _create_player(
    session,
    discord_id: int,
    name: str,
    gold: int = 0,
) -> int:
    now = datetime.now(UTC)
    player = PlayerModel(
        discord_id=discord_id,
        username=name.lower(),
        display_name=name,
        created_at=now,
        updated_at=now,
        last_seen_at=now,
    )
    session.add(player)
    session.flush()

    session.add_all(
        [
            PlayerProgressionModel(
                player_id=player.id, level=1, xp=0, skill_points=0,
                created_at=now, updated_at=now,
            ),
            PlayerResourceModel(
                player_id=player.id, gold=gold, daily_streak=0,
                created_at=now, updated_at=now,
            ),
        ]
    )
    session.commit()
    return player.id


def _create_item(session, code: str, name: str | None = None) -> int:
    now = datetime.now(UTC)
    item = ItemDefinitionModel(
        code=code,
        name=name or code,
        description="",
        category="resource",
        rarity="common",
        stackable=True,
        max_stack=None,
        sell_price=0,
        buy_price=None,
        icon=None,
        stat_bonuses_json=None,
        equipment_slot=None,
        requires_two_hands=False,
        created_at=now,
        updated_at=now,
    )
    session.add(item)
    session.commit()
    return item.id


def _give_item(session, player_id: int, item_id: int, quantity: int) -> None:
    now = datetime.now(UTC)
    session.add(
        PlayerInventoryItemModel(
            player_id=player_id,
            item_definition_id=item_id,
            quantity=quantity,
            created_at=now,
            updated_at=now,
        )
    )
    session.commit()


def _get_inventory(session, player_id: int) -> dict[str, int]:
    return {
        i.item_definition.code: i.quantity
        for i in InventoryRepository(session).list_by_player_id(player_id)
    }


def _get_gold(session, player_id: int) -> int:
    res = session.get(PlayerResourceModel, player_id)
    return res.gold if res else 0


def _make_create(session) -> CreateTradeUseCase:
    return CreateTradeUseCase(
        player_repository=PlayerRepository(session),
        inventory_repository=InventoryRepository(session),
        item_repository=ItemRepository(session),
        trade_repository=TradeRepository(session),
    )


def _make_accept(session) -> AcceptTradeUseCase:
    return AcceptTradeUseCase(
        session=session,
        player_repository=PlayerRepository(session),
        inventory_repository=InventoryRepository(session),
        item_repository=ItemRepository(session),
        trade_repository=TradeRepository(session),
    )


# ---------- CreateTrade ----------


def test_create_trade_succeeds_with_valid_offer(session):
    a = _create_player(session, 1, "Alice", gold=100)
    b = _create_player(session, 2, "Bob")
    iron = _create_item(session, "iron_ingot", "Lingot de fer")
    _give_item(session, a, iron, 5)

    result = _make_create(session).execute(
        initiator_discord_id=1,
        target_discord_id=2,
        initiator_username="alice",
        initiator_display_name="Alice",
        target_display_name="Bob",
        initiator_offer=TradeOffer(items=[("iron_ingot", 3)], gold=10),
        target_request=TradeOffer(items=[], gold=20),
    )

    assert result.success is True
    assert result.trade is not None
    assert result.trade.status == TradeStatus.PENDING
    # Aucun déplacement de ressources tant que pas accepté
    assert _get_inventory(session, a)["iron_ingot"] == 5
    assert _get_gold(session, a) == 100


def test_create_trade_rejects_self_trade(session):
    _create_player(session, 1, "Alice")

    result = _make_create(session).execute(
        initiator_discord_id=1,
        target_discord_id=1,
        initiator_username="alice",
        initiator_display_name="Alice",
        target_display_name="Alice",
        initiator_offer=TradeOffer(gold=10),
        target_request=TradeOffer(gold=10),
    )

    assert result.success is False
    assert "vous-même" in result.message.lower() or "vous meme" in result.message.lower()


def test_create_trade_rejects_when_initiator_lacks_items(session):
    _create_player(session, 1, "Alice")
    _create_player(session, 2, "Bob")
    iron = _create_item(session, "iron_ingot")
    _give_item(session, 1, iron, 1)  # n'a qu'un seul

    result = _make_create(session).execute(
        initiator_discord_id=1, target_discord_id=2,
        initiator_username="alice", initiator_display_name="Alice",
        target_display_name="Bob",
        initiator_offer=TradeOffer(items=[("iron_ingot", 5)]),
        target_request=TradeOffer(gold=10),
    )

    assert result.success is False


def test_create_trade_rejects_when_initiator_lacks_gold(session):
    _create_player(session, 1, "Alice", gold=10)
    _create_player(session, 2, "Bob")

    result = _make_create(session).execute(
        initiator_discord_id=1, target_discord_id=2,
        initiator_username="alice", initiator_display_name="Alice",
        target_display_name="Bob",
        initiator_offer=TradeOffer(gold=100),
        target_request=TradeOffer(gold=5),
    )

    assert result.success is False


def test_create_trade_rejects_unknown_item(session):
    _create_player(session, 1, "Alice")
    _create_player(session, 2, "Bob")

    result = _make_create(session).execute(
        initiator_discord_id=1, target_discord_id=2,
        initiator_username="alice", initiator_display_name="Alice",
        target_display_name="Bob",
        initiator_offer=TradeOffer(items=[("ghost_item", 1)]),
        target_request=TradeOffer(gold=5),
    )

    assert result.success is False
    assert "inconnu" in result.message.lower()


def test_create_trade_rejects_negative_gold(session):
    _create_player(session, 1, "Alice", gold=100)
    _create_player(session, 2, "Bob")

    result = _make_create(session).execute(
        initiator_discord_id=1, target_discord_id=2,
        initiator_username="alice", initiator_display_name="Alice",
        target_display_name="Bob",
        initiator_offer=TradeOffer(gold=-5),
        target_request=TradeOffer(gold=10),
    )

    assert result.success is False


def test_create_trade_rejects_empty_proposal(session):
    _create_player(session, 1, "Alice")
    _create_player(session, 2, "Bob")

    result = _make_create(session).execute(
        initiator_discord_id=1, target_discord_id=2,
        initiator_username="alice", initiator_display_name="Alice",
        target_display_name="Bob",
        initiator_offer=TradeOffer(),
        target_request=TradeOffer(),
    )

    assert result.success is False
    assert "vide" in result.message.lower()


def test_create_trade_rejects_existing_pending_between_pair(session):
    _create_player(session, 1, "Alice", gold=100)
    _create_player(session, 2, "Bob", gold=100)
    use_case = _make_create(session)

    # 1er trade OK
    r1 = use_case.execute(
        initiator_discord_id=1, target_discord_id=2,
        initiator_username="alice", initiator_display_name="Alice",
        target_display_name="Bob",
        initiator_offer=TradeOffer(gold=10),
        target_request=TradeOffer(gold=20),
    )
    assert r1.success is True

    # 2e tentative = refusée tant que le 1er est pending
    r2 = use_case.execute(
        initiator_discord_id=1, target_discord_id=2,
        initiator_username="alice", initiator_display_name="Alice",
        target_display_name="Bob",
        initiator_offer=TradeOffer(gold=5),
        target_request=TradeOffer(gold=5),
    )
    assert r2.success is False
    assert "pending" in r2.message.lower() or "existe" in r2.message.lower()


# ---------- AcceptTrade ----------


def test_accept_trade_swaps_items_and_gold_atomically(session):
    a = _create_player(session, 1, "Alice", gold=100)
    b = _create_player(session, 2, "Bob", gold=50)
    iron = _create_item(session, "iron_ingot")
    leather = _create_item(session, "leather_strip")
    _give_item(session, a, iron, 5)
    _give_item(session, b, leather, 3)

    create_result = _make_create(session).execute(
        initiator_discord_id=1, target_discord_id=2,
        initiator_username="alice", initiator_display_name="Alice",
        target_display_name="Bob",
        initiator_offer=TradeOffer(items=[("iron_ingot", 3)], gold=10),
        target_request=TradeOffer(items=[("leather_strip", 2)], gold=20),
    )
    assert create_result.success is True

    accept = _make_accept(session)
    result = accept.execute(
        trade_id=create_result.trade.id,
        accepting_player_discord_id=2,
    )

    assert result.success is True
    inv_a = _get_inventory(session, a)
    inv_b = _get_inventory(session, b)
    # Alice : -3 fer, +2 cuir, -10 +20 or = 110
    assert inv_a["iron_ingot"] == 2
    assert inv_a["leather_strip"] == 2
    assert _get_gold(session, a) == 110
    # Bob : +3 fer, -2 cuir, +10 -20 or = 40
    assert inv_b["iron_ingot"] == 3
    assert inv_b["leather_strip"] == 1
    assert _get_gold(session, b) == 40


def test_accept_trade_fails_if_initiator_consumed_items_in_meantime(session):
    """Sécurité : entre la proposition et l'acceptation, l'initiator a consommé
    son item proposé. L'accept doit échouer sans déplacer quoi que ce soit."""
    a = _create_player(session, 1, "Alice", gold=100)
    b = _create_player(session, 2, "Bob", gold=50)
    iron = _create_item(session, "iron_ingot")
    _give_item(session, a, iron, 3)

    create_result = _make_create(session).execute(
        initiator_discord_id=1, target_discord_id=2,
        initiator_username="alice", initiator_display_name="Alice",
        target_display_name="Bob",
        initiator_offer=TradeOffer(items=[("iron_ingot", 3)]),
        target_request=TradeOffer(gold=10),
    )
    trade_id = create_result.trade.id

    # Alice consomme tout son fer entre temps (genre via /craft)
    InventoryRepository(session).remove_item(a, iron, 3)

    result = _make_accept(session).execute(
        trade_id=trade_id, accepting_player_discord_id=2
    )

    assert result.success is False
    # Aucun changement : Bob garde tout son or, Alice n'a rien reçu
    assert _get_gold(session, b) == 50
    assert _get_gold(session, a) == 100
    # Le trade est marqué FAILED pour ne pas être réessayé
    refreshed = TradeRepository(session).get_by_id(trade_id)
    assert refreshed.status == TradeStatus.FAILED


def test_accept_trade_fails_if_target_lacks_gold_at_accept_time(session):
    a = _create_player(session, 1, "Alice")
    b = _create_player(session, 2, "Bob", gold=50)
    iron = _create_item(session, "iron_ingot")
    _give_item(session, a, iron, 5)

    create_result = _make_create(session).execute(
        initiator_discord_id=1, target_discord_id=2,
        initiator_username="alice", initiator_display_name="Alice",
        target_display_name="Bob",
        initiator_offer=TradeOffer(items=[("iron_ingot", 3)]),
        target_request=TradeOffer(gold=40),
    )
    trade_id = create_result.trade.id

    # Bob dépense son or entre temps
    bob_resources = session.get(PlayerResourceModel, b)
    bob_resources.gold = 10
    session.commit()

    result = _make_accept(session).execute(
        trade_id=trade_id, accepting_player_discord_id=2
    )

    assert result.success is False
    # Aucun déplacement : Alice garde son fer, Bob garde ses 10 or
    assert _get_inventory(session, a)["iron_ingot"] == 5
    assert _get_gold(session, b) == 10


def test_accept_trade_rejects_non_target(session):
    a = _create_player(session, 1, "Alice", gold=100)
    b = _create_player(session, 2, "Bob")
    c = _create_player(session, 3, "Charlie")

    create_result = _make_create(session).execute(
        initiator_discord_id=1, target_discord_id=2,
        initiator_username="alice", initiator_display_name="Alice",
        target_display_name="Bob",
        initiator_offer=TradeOffer(gold=10),
        target_request=TradeOffer(gold=5),
    )

    # Charlie tente d'accepter le trade qui ne le concerne pas
    result = _make_accept(session).execute(
        trade_id=create_result.trade.id,
        accepting_player_discord_id=3,
    )

    assert result.success is False


def test_accept_trade_rejects_when_already_accepted(session):
    a = _create_player(session, 1, "Alice", gold=100)
    b = _create_player(session, 2, "Bob", gold=50)

    create_result = _make_create(session).execute(
        initiator_discord_id=1, target_discord_id=2,
        initiator_username="alice", initiator_display_name="Alice",
        target_display_name="Bob",
        initiator_offer=TradeOffer(gold=10),
        target_request=TradeOffer(gold=5),
    )

    accept = _make_accept(session)
    accept.execute(trade_id=create_result.trade.id, accepting_player_discord_id=2)
    # 2ème acceptation
    result = accept.execute(
        trade_id=create_result.trade.id, accepting_player_discord_id=2
    )

    assert result.success is False
    # Une seule exécution du swap (pas de duplication d'or)
    assert _get_gold(session, a) == 95  # -10 + 5
    assert _get_gold(session, b) == 55  # -5 + 10


def test_accept_trade_rejects_when_expired(session):
    a = _create_player(session, 1, "Alice", gold=100)
    b = _create_player(session, 2, "Bob", gold=50)

    create_result = _make_create(session).execute(
        initiator_discord_id=1, target_discord_id=2,
        initiator_username="alice", initiator_display_name="Alice",
        target_display_name="Bob",
        initiator_offer=TradeOffer(gold=10),
        target_request=TradeOffer(gold=5),
    )

    # Force l'expiration
    trade = session.get(TradeModel, create_result.trade.id)
    trade.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    session.commit()

    result = _make_accept(session).execute(
        trade_id=create_result.trade.id,
        accepting_player_discord_id=2,
    )

    assert result.success is False
    refreshed = TradeRepository(session).get_by_id(create_result.trade.id)
    assert refreshed.status == TradeStatus.EXPIRED


# ---------- RefuseTrade & CancelTrade ----------


def test_refuse_trade_marks_refused(session):
    _create_player(session, 1, "Alice", gold=100)
    _create_player(session, 2, "Bob")

    create_result = _make_create(session).execute(
        initiator_discord_id=1, target_discord_id=2,
        initiator_username="alice", initiator_display_name="Alice",
        target_display_name="Bob",
        initiator_offer=TradeOffer(gold=10),
        target_request=TradeOffer(gold=5),
    )

    refuse = RefuseTradeUseCase(TradeRepository(session))
    result = refuse.execute(
        trade_id=create_result.trade.id,
        refusing_player_discord_id=2,
    )

    assert result.success is True
    assert result.trade.status == TradeStatus.REFUSED


def test_refuse_trade_rejects_non_target(session):
    _create_player(session, 1, "Alice", gold=100)
    _create_player(session, 2, "Bob")

    create_result = _make_create(session).execute(
        initiator_discord_id=1, target_discord_id=2,
        initiator_username="alice", initiator_display_name="Alice",
        target_display_name="Bob",
        initiator_offer=TradeOffer(gold=10),
        target_request=TradeOffer(gold=5),
    )

    refuse = RefuseTradeUseCase(TradeRepository(session))
    # Alice (initiator) tente de refuser son propre trade
    result = refuse.execute(
        trade_id=create_result.trade.id,
        refusing_player_discord_id=1,
    )

    assert result.success is False


def test_cancel_trade_by_initiator(session):
    _create_player(session, 1, "Alice", gold=100)
    _create_player(session, 2, "Bob")

    create_result = _make_create(session).execute(
        initiator_discord_id=1, target_discord_id=2,
        initiator_username="alice", initiator_display_name="Alice",
        target_display_name="Bob",
        initiator_offer=TradeOffer(gold=10),
        target_request=TradeOffer(gold=5),
    )

    cancel = CancelTradeUseCase(TradeRepository(session))
    result = cancel.execute(
        trade_id=create_result.trade.id,
        cancelling_player_discord_id=1,
    )

    assert result.success is True
    assert result.trade.status == TradeStatus.CANCELLED


def test_cancel_trade_rejects_non_initiator(session):
    _create_player(session, 1, "Alice", gold=100)
    _create_player(session, 2, "Bob")

    create_result = _make_create(session).execute(
        initiator_discord_id=1, target_discord_id=2,
        initiator_username="alice", initiator_display_name="Alice",
        target_display_name="Bob",
        initiator_offer=TradeOffer(gold=10),
        target_request=TradeOffer(gold=5),
    )

    cancel = CancelTradeUseCase(TradeRepository(session))
    # Bob (target) tente d'annuler le trade dont Alice est l'initiator
    result = cancel.execute(
        trade_id=create_result.trade.id,
        cancelling_player_discord_id=2,
    )

    assert result.success is False
