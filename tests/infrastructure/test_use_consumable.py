"""Tests d'intégration du UseConsumableUseCase (potions de soin)."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application.use_cases.use_consumable import UseConsumableUseCase
from app.domain.services.stats_service import StatsService
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

from app.infrastructure.db.repositories.class_repository import ClassRepository
from app.infrastructure.db.repositories.equipment_repository import EquipmentRepository
from app.infrastructure.db.repositories.inventory_repository import InventoryRepository
from app.infrastructure.db.repositories.item_repository import ItemRepository
from app.infrastructure.db.repositories.player_health_repository import (
    PlayerHealthRepository,
)
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.repositories.player_skill_allocation_repository import (
    PlayerSkillAllocationRepository,
)


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


def _seed_potion(session, code: str, percent: int) -> int:
    now = datetime.now(UTC)
    item = ItemDefinitionModel(
        code=code,
        name=f"Potion {percent}",
        description=f"Restaure {percent}% PV",
        category="consumable",
        rarity="common",
        stackable=True,
        max_stack=None,
        sell_price=10,
        buy_price=30,
        icon=None,
        stat_bonuses_json={"effect": "heal_percent", "value": percent},
        equipment_slot=None,
        requires_two_hands=False,
        created_at=now,
        updated_at=now,
    )
    session.add(item)
    session.commit()
    return item.id


def _build_use_case(session):
    return UseConsumableUseCase(
        player_repository=PlayerRepository(session),
        item_repository=ItemRepository(session),
        inventory_repository=InventoryRepository(session),
        equipment_repository=EquipmentRepository(session),
        class_repository=ClassRepository(session),
        skill_allocation_repository=PlayerSkillAllocationRepository(session),
        health_repository=PlayerHealthRepository(session),
        stats_service=StatsService(),
    )


def test_potion_50_percent_heals_correctly(session):
    item_id = _seed_potion(session, "potion_soin_i", 50)
    use_case = _build_use_case(session)

    # Premier appel auto-create profile + ajoute la potion en inventaire
    profile = PlayerRepository(session).get_or_create_by_discord_id(
        discord_id=1, username="alice", display_name="Alice",
    )
    InventoryRepository(session).add_item(profile.player.id, item_id, 1)

    # Pose current_hp à 0 (profil au max_hp ~15-20 selon level 1)
    health_repo = PlayerHealthRepository(session)
    stats = StatsService().calculate_player_stats(
        profile=profile, equipped_items=[], active_class=None,
    )
    health_repo.get_or_create(profile.player.id, default_current_hp=stats.max_hp)
    health_repo.update_current_hp(profile.player.id, 0)

    result = use_case.execute(
        discord_id=1, username="alice", display_name="Alice",
        item_code="potion_soin_i",
    )

    assert result.success is True
    assert result.hp_before == 0
    # 50% de max_hp restauré
    assert result.hp_after == round(stats.max_hp * 0.5)


def test_potion_caps_at_max_hp(session):
    """Potion 100% sur HP déjà presque pleins ne dépasse pas max_hp."""
    item_id = _seed_potion(session, "potion_soin_iii", 100)
    use_case = _build_use_case(session)

    profile = PlayerRepository(session).get_or_create_by_discord_id(
        discord_id=1, username="alice", display_name="Alice",
    )
    InventoryRepository(session).add_item(profile.player.id, item_id, 1)

    stats = StatsService().calculate_player_stats(
        profile=profile, equipped_items=[], active_class=None,
    )
    health_repo = PlayerHealthRepository(session)
    health_repo.get_or_create(profile.player.id, default_current_hp=stats.max_hp)
    # Déjà full HP
    health_repo.update_current_hp(profile.player.id, stats.max_hp)

    result = use_case.execute(
        discord_id=1, username="alice", display_name="Alice",
        item_code="potion_soin_iii",
    )

    assert result.success is True
    assert result.hp_after == stats.max_hp  # cap


def test_potion_consumes_from_inventory(session):
    item_id = _seed_potion(session, "potion_soin_i", 50)
    use_case = _build_use_case(session)

    profile = PlayerRepository(session).get_or_create_by_discord_id(
        discord_id=1, username="alice", display_name="Alice",
    )
    inv_repo = InventoryRepository(session)
    inv_repo.add_item(profile.player.id, item_id, 3)

    use_case.execute(
        discord_id=1, username="alice", display_name="Alice",
        item_code="potion_soin_i",
    )

    # Reste 2 en inventaire
    inv = inv_repo.list_by_player_id(profile.player.id)
    assert len(inv) == 1
    assert inv[0].quantity == 2


def test_use_refused_if_not_in_inventory(session):
    _seed_potion(session, "potion_soin_i", 50)
    use_case = _build_use_case(session)

    PlayerRepository(session).get_or_create_by_discord_id(
        discord_id=1, username="alice", display_name="Alice",
    )

    result = use_case.execute(
        discord_id=1, username="alice", display_name="Alice",
        item_code="potion_soin_i",
    )
    assert result.success is False
    assert "inventaire" in result.message


def test_use_refused_if_not_consumable(session):
    """Tenter d'utiliser un item non-consommable est refusé."""
    now = datetime.now(UTC)
    item = ItemDefinitionModel(
        code="iron_sword",
        name="Épée en fer",
        description="",
        category="weapon",
        rarity="common",
        stackable=False,
        max_stack=None,
        sell_price=20,
        buy_price=None,
        icon=None,
        stat_bonuses_json={"attack": 5},
        equipment_slot="main_droite",
        requires_two_hands=False,
        created_at=now,
        updated_at=now,
    )
    session.add(item)
    session.commit()

    use_case = _build_use_case(session)
    PlayerRepository(session).get_or_create_by_discord_id(
        discord_id=1, username="alice", display_name="Alice",
    )

    result = use_case.execute(
        discord_id=1, username="alice", display_name="Alice",
        item_code="iron_sword",
    )
    assert result.success is False
    assert "consommable" in result.message
