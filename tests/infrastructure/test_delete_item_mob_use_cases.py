"""Tests du cascade delete : DeleteItemUseCase / DeleteMobUseCase retirent
l'entité ET toutes ses références, sans toucher au reste."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.application.use_cases.delete_item import DeleteItemUseCase
from app.application.use_cases.delete_mob import DeleteMobUseCase
from app.infrastructure.db.base import Base

from app.infrastructure.db.models.player_model import PlayerModel
from app.infrastructure.db.models.item_model import ItemDefinitionModel
from app.infrastructure.db.models.inventory_model import PlayerInventoryItemModel
from app.infrastructure.db.models.equipment_model import PlayerEquipmentItemModel
from app.infrastructure.db.models.shop_item_model import ShopItemModel
from app.infrastructure.db.models.craft_model import (
    CraftRecipeModel, CraftRecipeIngredientModel,
)
from app.infrastructure.db.models.mob_model import MobDefinitionModel
from app.infrastructure.db.models.player_mob_kill_model import PlayerMobKillModel

# Import de tous les modèles pour que les relationships SQLAlchemy se résolvent.
from app.infrastructure.db.models.progression_model import PlayerProgressionModel  # noqa: F401
from app.infrastructure.db.models.resource_model import PlayerResourceModel  # noqa: F401
from app.infrastructure.db.models.class_model import ClassDefinitionModel  # noqa: F401
from app.infrastructure.db.models.player_class_state_model import PlayerClassStateModel  # noqa: F401
from app.infrastructure.db.models.cooldown_model import PlayerCooldownModel  # noqa: F401
from app.infrastructure.db.models.player_health_state_model import PlayerHealthStateModel  # noqa: F401
from app.infrastructure.db.models.player_career_stats_model import PlayerCareerStatsModel  # noqa: F401
from app.infrastructure.db.models.player_skill_allocation_model import PlayerSkillAllocationModel  # noqa: F401
from app.infrastructure.db.models.trade_model import TradeModel, TradeItemModel  # noqa: F401
from app.infrastructure.db.models.marketplace_listing_model import MarketplaceListingModel  # noqa: F401
from app.infrastructure.db.models.equipment_set_model import (  # noqa: F401
    PlayerEquipmentSetModel, PlayerEquipmentSetItemModel,
)
from app.infrastructure.db.models.player_duel_rank_model import PlayerDuelRankModel  # noqa: F401
from app.infrastructure.db.models.player_title_model import PlayerTitleModel  # noqa: F401
from app.infrastructure.db.models.profession_model import (  # noqa: F401
    PlayerProfessionModel, ProfessionDefinitionModel,
)
from app.infrastructure.db.models.quest_model import (  # noqa: F401
    QuestDefinitionModel, PlayerQuestStateModel,
)
from app.infrastructure.db.models.weekly_quest_model import WeeklyQuestAssignmentModel  # noqa: F401
from app.infrastructure.db.models.daily_quest_model import DailyQuestAssignmentModel  # noqa: F401
from app.infrastructure.db.models.world_boss_model import (  # noqa: F401
    WorldBossModel, WorldBossParticipationModel,
)
from app.infrastructure.db.models.help_subscriber_model import HelpSubscriberModel  # noqa: F401


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()
        engine.dispose()


def _item(session, code, **kw):
    now = datetime.now(UTC)
    it = ItemDefinitionModel(
        code=code, name=code.title(), description="", category="weapon",
        rarity="common", stackable=False, max_stack=None, sell_price=1,
        buy_price=None, icon=None, stat_bonuses_json=None,
        equipment_slot="main_droite", requires_two_hands=False,
        created_at=now, updated_at=now, **kw,
    )
    session.add(it); session.flush()
    return it


def _player(session):
    now = datetime.now(UTC)
    p = PlayerModel(discord_id=1, username="u", display_name="U",
                    created_at=now, updated_at=now)
    session.add(p); session.flush()
    return p


def test_delete_item_removes_all_references(session):
    now = datetime.now(UTC)
    target = _item(session, "iron_sword")
    control = _item(session, "gobelin_axe")  # doit survivre
    p = _player(session)

    # Références au target dans plusieurs tables
    session.add(PlayerInventoryItemModel(player_id=p.id, item_definition_id=target.id,
                                         quantity=3, created_at=now, updated_at=now))
    session.add(PlayerEquipmentItemModel(player_id=p.id, item_definition_id=target.id,
                                         slot="main_droite", created_at=now, updated_at=now))
    session.add(ShopItemModel(item_definition_id=target.id, buy_price=10,
                              max_sell_price=5, min_sell_price=1, stock_threshold=100,
                              current_stock=0, enabled=True, created_at=now, updated_at=now))
    recipe = CraftRecipeModel(code="iron_sword_recipe", name="Épée",
                              result_item_definition_id=target.id, result_quantity=1,
                              created_at=now, updated_at=now)
    session.add(recipe); session.flush()
    session.add(CraftRecipeIngredientModel(craft_recipe_id=recipe.id,
                                           item_definition_id=control.id, quantity=2))
    # control aussi en inventaire (doit rester)
    session.add(PlayerInventoryItemModel(player_id=p.id, item_definition_id=control.id,
                                         quantity=1, created_at=now, updated_at=now))
    session.commit()

    result = DeleteItemUseCase().execute(session, "iron_sword")

    assert result.deleted is True
    # L'item cible et TOUTES ses refs sont parties
    assert session.execute(select(ItemDefinitionModel).where(
        ItemDefinitionModel.code == "iron_sword")).scalar_one_or_none() is None
    assert session.execute(select(PlayerInventoryItemModel).where(
        PlayerInventoryItemModel.item_definition_id == target.id)).first() is None
    assert session.execute(select(PlayerEquipmentItemModel).where(
        PlayerEquipmentItemModel.item_definition_id == target.id)).first() is None
    assert session.execute(select(ShopItemModel).where(
        ShopItemModel.item_definition_id == target.id)).first() is None
    # La recette produisant l'item + ses ingrédients sont parties
    assert session.execute(select(CraftRecipeModel)).first() is None
    assert session.execute(select(CraftRecipeIngredientModel)).first() is None
    # Le control survit (item + son inventaire)
    assert session.execute(select(ItemDefinitionModel).where(
        ItemDefinitionModel.code == "gobelin_axe")).scalar_one_or_none() is not None
    assert session.execute(select(PlayerInventoryItemModel).where(
        PlayerInventoryItemModel.item_definition_id == control.id)).first() is not None


def test_delete_item_absent_returns_false(session):
    assert DeleteItemUseCase().execute(session, "inexistant").deleted is False


def test_delete_mob_removes_kills(session):
    now = datetime.now(UTC)
    mob = MobDefinitionModel(
        code="slime", name="Slime", description="", image_name="",
        family="slime", max_hp=100, current_hp=100, attack=10, defense=5,
        speed=5, crit_chance=0, crit_damage=100, dodge=0, hp_regeneration=0,
        xp_reward=10, gold_reward=5, spawn_weight=10, loot_table_json=None,
        created_at=now, updated_at=now,
    )
    session.add(mob)
    p = _player(session)
    session.add(PlayerMobKillModel(player_id=p.id, mob_code="slime", kill_count=7))
    session.commit()

    result = DeleteMobUseCase().execute(session, "slime")

    assert result.deleted is True
    assert result.kills_removed == 1
    assert session.execute(select(MobDefinitionModel).where(
        MobDefinitionModel.code == "slime")).scalar_one_or_none() is None
    assert session.execute(select(PlayerMobKillModel).where(
        PlayerMobKillModel.mob_code == "slime")).first() is None
