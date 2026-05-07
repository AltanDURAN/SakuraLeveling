"""Tests des use cases /craft_panoplie et /forge_panoplie.

Couvre :
- plan vide quand toutes les pièces sont possédées
- plan correct : items manquants ↔ recettes ↔ ingrédients agrégés
- détection ressources insuffisantes (missing_ingredients)
- filtre forge / craft par catégorie d'item
- exécution : ingrédients consommés, items produits
"""

from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application.use_cases.panoplie_crafts import (
    BuildPanoplieCraftPlanUseCase,
    ExecutePanoplieCraftsUseCase,
)
from app.infrastructure.db.base import Base
from app.infrastructure.db.models.player_model import PlayerModel
from app.infrastructure.db.models.progression_model import PlayerProgressionModel  # noqa: F401
from app.infrastructure.db.models.resource_model import PlayerResourceModel  # noqa: F401
from app.infrastructure.db.models.item_model import ItemDefinitionModel
from app.infrastructure.db.models.inventory_model import PlayerInventoryItemModel  # noqa: F401
from app.infrastructure.db.models.equipment_model import PlayerEquipmentItemModel  # noqa: F401
from app.infrastructure.db.models.mob_model import MobDefinitionModel  # noqa: F401
from app.infrastructure.db.models.class_model import ClassDefinitionModel  # noqa: F401
from app.infrastructure.db.models.player_class_state_model import PlayerClassStateModel  # noqa: F401
from app.infrastructure.db.models.craft_model import (
    CraftRecipeModel, CraftRecipeIngredientModel,
)
from app.infrastructure.db.models.cooldown_model import PlayerCooldownModel  # noqa: F401
from app.infrastructure.db.models.quest_model import QuestDefinitionModel, PlayerQuestStateModel  # noqa: F401
from app.infrastructure.db.models.profession_model import PlayerProfessionModel  # noqa: F401
from app.infrastructure.db.models.player_health_state_model import PlayerHealthStateModel  # noqa: F401
from app.infrastructure.db.models.player_mob_kill_model import PlayerMobKillModel  # noqa: F401
from app.infrastructure.db.models.shop_item_model import ShopItemModel  # noqa: F401
from app.infrastructure.db.models.player_career_stats_model import PlayerCareerStatsModel  # noqa: F401
from app.infrastructure.db.models.player_skill_allocation_model import PlayerSkillAllocationModel  # noqa: F401

from app.infrastructure.db.repositories.craft_repository import CraftRepository
from app.infrastructure.db.repositories.equipment_repository import EquipmentRepository
from app.infrastructure.db.repositories.inventory_repository import InventoryRepository
from app.infrastructure.db.repositories.item_repository import ItemRepository
from app.infrastructure.db.repositories.player_repository import PlayerRepository


_FAKE_SETS = {
    "iron": {"name": "Fer", "icon": "🛡️", "tiers": []},
}


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    try:
        yield s
    finally:
        s.close()
        engine.dispose()


def _create_player(session, discord_id=1):
    now = datetime.now(UTC)
    p = PlayerModel(
        discord_id=discord_id, username="alpha", display_name="Alpha",
        created_at=now, updated_at=now, last_seen_at=now,
    )
    session.add(p)
    session.flush()
    session.add_all([
        PlayerProgressionModel(
            player_id=p.id, level=1, xp=0, skill_points=0,
            created_at=now, updated_at=now,
        ),
        PlayerResourceModel(
            player_id=p.id, gold=0, created_at=now, updated_at=now,
        ),
    ])
    session.commit()
    return p.id


def _create_item(
    session, code, category, equipment_slot=None, family="",
):
    now = datetime.now(UTC)
    item = ItemDefinitionModel(
        code=code, name=code.replace("_", " ").title(), description="",
        category=category, rarity="common",
        stackable=False, max_stack=None,
        sell_price=0, buy_price=None, icon=None,
        stat_bonuses_json=None,
        equipment_slot=equipment_slot,
        requires_two_hands=False,
        family=family,
        created_at=now, updated_at=now,
    )
    session.add(item)
    session.commit()
    return item.id


def _id_for_code(session, code: str) -> int:
    item = session.query(ItemDefinitionModel).filter_by(code=code).one()
    return item.id


def _create_recipe(session, code, result_code, ingredients):
    """ingredients : list of (item_code, qty)."""
    now = datetime.now(UTC)
    result_id = _id_for_code(session, result_code)
    recipe = CraftRecipeModel(
        code=code, name=code, result_item_definition_id=result_id,
        result_quantity=1, created_at=now, updated_at=now,
    )
    session.add(recipe)
    session.flush()
    for ic, qty in ingredients:
        ing_id = _id_for_code(session, ic)
        session.add(CraftRecipeIngredientModel(
            craft_recipe_id=recipe.id, item_definition_id=ing_id,
            quantity=qty,
        ))
    session.commit()


def _give(session, pid, item_id, qty=1):
    now = datetime.now(UTC)
    session.add(PlayerInventoryItemModel(
        player_id=pid, item_definition_id=item_id, quantity=qty,
        created_at=now, updated_at=now,
    ))
    session.commit()


def _make_build_uc(session):
    return BuildPanoplieCraftPlanUseCase(
        player_repository=PlayerRepository(session),
        inventory_repository=InventoryRepository(session),
        equipment_repository=EquipmentRepository(session),
        item_repository=ItemRepository(session),
        craft_repository=CraftRepository(session),
    )


def _make_exec_uc(session):
    return ExecutePanoplieCraftsUseCase(
        player_repository=PlayerRepository(session),
        inventory_repository=InventoryRepository(session),
        item_repository=ItemRepository(session),
    )


@patch(
    "app.application.use_cases.panoplie_crafts.list_set_definitions",
    return_value=_FAKE_SETS,
)
def test_unknown_family_returns_error(_, session):
    pid = _create_player(session)
    plan, error = _make_build_uc(session).execute(
        discord_id=1, username="a", display_name="A",
        family="unknown", station="craft",
    )
    assert plan is None
    assert "introuvable" in error


@patch(
    "app.application.use_cases.panoplie_crafts.list_set_definitions",
    return_value=_FAKE_SETS,
)
def test_plan_for_forge_filters_to_forge_categories(_, session):
    pid = _create_player(session)
    # 1 item forge (helmet) + 1 craft (necklace), tous iron
    helmet_id = _create_item(session, "iron_helmet", "helmet", "casque", "iron")
    necklace_id = _create_item(session, "iron_collier", "necklace", "collier", "iron")
    # Ingrédients
    _create_item(session, "iron_ingot", "resource")
    _create_recipe(session, "iron_helmet_recipe", "iron_helmet", [("iron_ingot", 4)])
    _create_recipe(session, "iron_collier_recipe", "iron_collier", [("iron_ingot", 4)])

    plan, _err = _make_build_uc(session).execute(
        discord_id=1, username="a", display_name="A",
        family="iron", station="forge",
    )
    assert plan is not None
    assert len(plan.entries) == 1
    assert plan.entries[0].result_item.code == "iron_helmet"


@patch(
    "app.application.use_cases.panoplie_crafts.list_set_definitions",
    return_value=_FAKE_SETS,
)
def test_already_owned_items_skipped(_, session):
    pid = _create_player(session)
    helmet_id = _create_item(session, "iron_helmet", "helmet", "casque", "iron")
    chest_id = _create_item(session, "iron_chest", "chest", "plastron", "iron")
    _create_item(session, "iron_ingot", "resource")
    _create_recipe(session, "iron_helmet_recipe", "iron_helmet", [("iron_ingot", 4)])
    _create_recipe(session, "iron_chest_recipe", "iron_chest", [("iron_ingot", 6)])
    # Le casque est déjà possédé
    _give(session, pid, helmet_id, 1)

    plan, _err = _make_build_uc(session).execute(
        discord_id=1, username="a", display_name="A",
        family="iron", station="forge",
    )
    assert len(plan.entries) == 1
    assert plan.entries[0].result_item.code == "iron_chest"
    assert len(plan.already_owned) == 1


@patch(
    "app.application.use_cases.panoplie_crafts.list_set_definitions",
    return_value=_FAKE_SETS,
)
def test_insufficient_resources_listed(_, session):
    pid = _create_player(session)
    _create_item(session, "iron_helmet", "helmet", "casque", "iron")
    _create_item(session, "iron_chest", "chest", "plastron", "iron")
    iron_ingot_id = _create_item(session, "iron_ingot", "resource")
    _create_recipe(session, "iron_helmet_recipe", "iron_helmet", [("iron_ingot", 4)])
    _create_recipe(session, "iron_chest_recipe", "iron_chest", [("iron_ingot", 6)])
    # Donne juste 5 lingots — il faut 4+6=10
    _give(session, pid, iron_ingot_id, 5)

    plan, _err = _make_build_uc(session).execute(
        discord_id=1, username="a", display_name="A",
        family="iron", station="forge",
    )
    assert plan.sufficient is False
    assert plan.missing_ingredients["iron_ingot"] == 5


@patch(
    "app.application.use_cases.panoplie_crafts.list_set_definitions",
    return_value=_FAKE_SETS,
)
def test_execute_consumes_ingredients_and_produces_items(_, session):
    pid = _create_player(session)
    _create_item(session, "iron_helmet", "helmet", "casque", "iron")
    iron_ingot_id = _create_item(session, "iron_ingot", "resource")
    _create_recipe(session, "iron_helmet_recipe", "iron_helmet", [("iron_ingot", 4)])
    _give(session, pid, iron_ingot_id, 4)

    plan, _err = _make_build_uc(session).execute(
        discord_id=1, username="a", display_name="A",
        family="iron", station="forge",
    )
    assert plan.sufficient is True

    result = _make_exec_uc(session).execute(
        discord_id=1, username="a", display_name="A", plan=plan,
    )
    assert result.success is True
    assert len(result.crafted_items) == 1

    inv = InventoryRepository(session).list_by_player_id(pid)
    by_code = {i.item_definition.code: i.quantity for i in inv}
    # Lingots consommés
    assert by_code.get("iron_ingot", 0) == 0
    # Casque produit
    assert by_code.get("iron_helmet", 0) == 1


@patch(
    "app.application.use_cases.panoplie_crafts.list_set_definitions",
    return_value=_FAKE_SETS,
)
def test_empty_plan_when_all_owned(_, session):
    pid = _create_player(session)
    helmet_id = _create_item(session, "iron_helmet", "helmet", "casque", "iron")
    _create_item(session, "iron_ingot", "resource")
    _create_recipe(session, "iron_helmet_recipe", "iron_helmet", [("iron_ingot", 4)])
    _give(session, pid, helmet_id, 1)

    plan, _err = _make_build_uc(session).execute(
        discord_id=1, username="a", display_name="A",
        family="iron", station="forge",
    )
    assert plan.is_empty is True
    assert len(plan.already_owned) == 1
