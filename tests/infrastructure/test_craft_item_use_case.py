"""Tests d'intégration de CraftItemUseCase (logique derrière /craft et /forge).

Comme /craft et /forge délèguent à CraftItemUseCase + filtrent par catégorie
au niveau cog, tester l'use case couvre les invariants critiques (consommation
des ingrédients, ajout du résultat, refus si stock insuffisant).
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application.use_cases.craft_item import CraftItemUseCase
from app.domain.services.craft_service import CraftService
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

from app.infrastructure.db.repositories.craft_repository import CraftRepository
from app.infrastructure.db.repositories.inventory_repository import InventoryRepository
from app.infrastructure.db.repositories.item_repository import ItemRepository
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


def _create_player(session, discord_id: int = 1) -> int:
    now = datetime.now(UTC)
    player = PlayerModel(
        discord_id=discord_id,
        username="alpha",
        display_name="Alpha",
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
                player_id=player.id, gold=0,
                created_at=now, updated_at=now,
            ),
        ]
    )
    session.commit()
    return player.id


def _create_item(
    session,
    code: str,
    name: str = "Item",
    category: str = "resource",
    equipment_slot: str | None = None,
) -> int:
    now = datetime.now(UTC)
    item = ItemDefinitionModel(
        code=code,
        name=name,
        description="",
        category=category,
        rarity="common",
        stackable=True,
        max_stack=None,
        sell_price=0,
        buy_price=None,
        icon=None,
        stat_bonuses_json=None,
        equipment_slot=equipment_slot,
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


def _create_recipe(
    session,
    code: str,
    result_item_id: int,
    result_quantity: int = 1,
    ingredients: list[tuple[int, int]] | None = None,
) -> None:
    """Crée une recette de craft : ingredients = liste de (item_definition_id, quantity)."""
    repo = CraftRepository(session)
    repo.create(
        code=code,
        name=code,
        result_item_definition_id=result_item_id,
        result_quantity=result_quantity,
        ingredients=ingredients or [],
    )


def _make_use_case(session) -> CraftItemUseCase:
    return CraftItemUseCase(
        player_repository=PlayerRepository(session),
        craft_repository=CraftRepository(session),
        inventory_repository=InventoryRepository(session),
        item_repository=ItemRepository(session),
        craft_service=CraftService(),
    )


def test_craft_succeeds_when_all_ingredients_present(session):
    pid = _create_player(session)
    iron_id = _create_item(session, "iron")
    leather_id = _create_item(session, "leather")
    helmet_id = _create_item(session, "helmet", category="helmet", equipment_slot="casque")
    _give_item(session, pid, iron_id, quantity=5)
    _give_item(session, pid, leather_id, quantity=2)
    _create_recipe(
        session, "helmet_recipe", helmet_id,
        ingredients=[(iron_id, 4), (leather_id, 1)],
    )

    success = _make_use_case(session).execute(
        discord_id=1, username="alpha", display_name="Alpha", recipe_code="helmet_recipe"
    )

    assert success is True
    inventory = InventoryRepository(session).list_by_player_id(pid)
    by_code = {i.item_definition.code: i.quantity for i in inventory}
    # Ingrédients consommés
    assert by_code.get("iron") == 1  # 5 - 4
    assert by_code.get("leather") == 1  # 2 - 1
    # Résultat ajouté
    assert by_code.get("helmet") == 1


def test_craft_fails_when_recipe_does_not_exist(session):
    _create_player(session)

    success = _make_use_case(session).execute(
        discord_id=1, username="alpha", display_name="Alpha", recipe_code="ghost_recipe"
    )

    assert success is False


def test_craft_fails_when_ingredients_insufficient(session):
    pid = _create_player(session)
    iron_id = _create_item(session, "iron")
    helmet_id = _create_item(session, "helmet")
    _give_item(session, pid, iron_id, quantity=2)
    _create_recipe(
        session, "helmet_recipe", helmet_id, ingredients=[(iron_id, 5)],
    )

    success = _make_use_case(session).execute(
        discord_id=1, username="alpha", display_name="Alpha", recipe_code="helmet_recipe"
    )

    assert success is False
    # Ingrédients NON consommés (échec atomique)
    inventory = InventoryRepository(session).list_by_player_id(pid)
    by_code = {i.item_definition.code: i.quantity for i in inventory}
    assert by_code.get("iron") == 2


def test_craft_fails_when_no_ingredients_in_inventory(session):
    _create_player(session)
    iron_id = _create_item(session, "iron")
    helmet_id = _create_item(session, "helmet")
    _create_recipe(
        session, "helmet_recipe", helmet_id, ingredients=[(iron_id, 1)],
    )
    # Aucun give_item

    success = _make_use_case(session).execute(
        discord_id=1, username="alpha", display_name="Alpha", recipe_code="helmet_recipe"
    )

    assert success is False


def test_craft_with_quantity_greater_than_one(session):
    pid = _create_player(session)
    log_id = _create_item(session, "log")
    plank_id = _create_item(session, "plank")
    _give_item(session, pid, log_id, quantity=10)
    _create_recipe(
        session, "plank_recipe", plank_id,
        result_quantity=4,
        ingredients=[(log_id, 1)],
    )

    success = _make_use_case(session).execute(
        discord_id=1, username="alpha", display_name="Alpha", recipe_code="plank_recipe"
    )

    assert success is True
    inventory = InventoryRepository(session).list_by_player_id(pid)
    by_code = {i.item_definition.code: i.quantity for i in inventory}
    assert by_code.get("log") == 9
    assert by_code.get("plank") == 4


def test_craft_consumes_then_produces_for_chained_resource(session):
    """Si un ingrédient est consommé puis recraft à partir d'autres, le flux marche."""
    pid = _create_player(session)
    log_id = _create_item(session, "log")
    plank_id = _create_item(session, "plank")
    chair_id = _create_item(session, "chair")

    _give_item(session, pid, log_id, quantity=4)
    _create_recipe(
        session, "plank_recipe", plank_id,
        ingredients=[(log_id, 2)],
    )
    _create_recipe(
        session, "chair_recipe", chair_id,
        ingredients=[(plank_id, 1)],
    )

    use_case = _make_use_case(session)

    # 1er craft : 2 logs → 1 plank
    assert use_case.execute(1, "alpha", "Alpha", "plank_recipe") is True
    # 2e craft : 1 plank → 1 chair
    assert use_case.execute(1, "alpha", "Alpha", "chair_recipe") is True

    inventory = InventoryRepository(session).list_by_player_id(pid)
    by_code = {i.item_definition.code: i.quantity for i in inventory}
    assert by_code.get("log") == 2  # 4 - 2
    assert by_code.get("chair") == 1
    # plank consommé entièrement, plus dans l'inventaire (rangée supprimée à 0)
    assert "plank" not in by_code or by_code.get("plank") == 0


def test_craft_can_be_repeated_until_resources_exhausted(session):
    pid = _create_player(session)
    log_id = _create_item(session, "log")
    plank_id = _create_item(session, "plank")
    _give_item(session, pid, log_id, quantity=6)
    _create_recipe(
        session, "plank_recipe", plank_id, ingredients=[(log_id, 2)],
    )

    use_case = _make_use_case(session)
    assert use_case.execute(1, "alpha", "Alpha", "plank_recipe") is True
    assert use_case.execute(1, "alpha", "Alpha", "plank_recipe") is True
    assert use_case.execute(1, "alpha", "Alpha", "plank_recipe") is True
    # 4e tentative : plus de logs
    assert use_case.execute(1, "alpha", "Alpha", "plank_recipe") is False

    inventory = InventoryRepository(session).list_by_player_id(pid)
    by_code = {i.item_definition.code: i.quantity for i in inventory}
    assert by_code.get("plank") == 3
