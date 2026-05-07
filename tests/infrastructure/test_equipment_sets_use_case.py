"""Tests des use cases /create_set, /delete_set, /equip_set, /unequip all."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application.use_cases.equipment_sets import (
    CreateEquipmentSetUseCase,
    DeleteEquipmentSetUseCase,
    EquipSavedSetUseCase,
    UnequipAllUseCase,
)
from app.infrastructure.db.base import Base
from app.infrastructure.db.models.player_model import PlayerModel
from app.infrastructure.db.models.progression_model import PlayerProgressionModel  # noqa: F401
from app.infrastructure.db.models.resource_model import PlayerResourceModel  # noqa: F401
from app.infrastructure.db.models.item_model import ItemDefinitionModel
from app.infrastructure.db.models.inventory_model import PlayerInventoryItemModel  # noqa: F401
from app.infrastructure.db.models.equipment_model import PlayerEquipmentItemModel  # noqa: F401
from app.infrastructure.db.models.equipment_set_model import (  # noqa: F401
    PlayerEquipmentSetModel,
    PlayerEquipmentSetItemModel,
)
from app.infrastructure.db.models.mob_model import MobDefinitionModel  # noqa: F401
from app.infrastructure.db.models.class_model import ClassDefinitionModel  # noqa: F401
from app.infrastructure.db.models.player_class_state_model import PlayerClassStateModel  # noqa: F401
from app.infrastructure.db.models.craft_model import (  # noqa: F401
    CraftRecipeModel, CraftRecipeIngredientModel,
)
from app.infrastructure.db.models.cooldown_model import PlayerCooldownModel  # noqa: F401
from app.infrastructure.db.models.quest_model import (  # noqa: F401
    QuestDefinitionModel, PlayerQuestStateModel,
)
from app.infrastructure.db.models.profession_model import PlayerProfessionModel  # noqa: F401
from app.infrastructure.db.models.player_health_state_model import PlayerHealthStateModel  # noqa: F401
from app.infrastructure.db.models.player_mob_kill_model import PlayerMobKillModel  # noqa: F401
from app.infrastructure.db.models.shop_item_model import ShopItemModel  # noqa: F401
from app.infrastructure.db.models.player_career_stats_model import PlayerCareerStatsModel  # noqa: F401
from app.infrastructure.db.models.player_skill_allocation_model import PlayerSkillAllocationModel  # noqa: F401

from app.infrastructure.db.repositories.equipment_repository import EquipmentRepository
from app.infrastructure.db.repositories.equipment_set_repository import (
    EquipmentSetRepository,
)
from app.infrastructure.db.repositories.inventory_repository import InventoryRepository
from app.infrastructure.db.repositories.player_repository import PlayerRepository


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
    session, code, category, slot, requires_two_hands=False,
):
    now = datetime.now(UTC)
    item = ItemDefinitionModel(
        code=code, name=code.replace("_", " ").title(), description="",
        category=category, rarity="common",
        stackable=False, max_stack=None,
        sell_price=0, buy_price=None, icon=None,
        stat_bonuses_json=None, equipment_slot=slot,
        requires_two_hands=requires_two_hands, family="",
        created_at=now, updated_at=now,
    )
    session.add(item)
    session.commit()
    return item.id


def _give(session, pid, item_id, qty=1):
    now = datetime.now(UTC)
    session.add(PlayerInventoryItemModel(
        player_id=pid, item_definition_id=item_id, quantity=qty,
        created_at=now, updated_at=now,
    ))
    session.commit()


def _equip_pre(session, pid, item_id, slot):
    now = datetime.now(UTC)
    session.add(PlayerEquipmentItemModel(
        player_id=pid, item_definition_id=item_id, slot=slot,
        created_at=now, updated_at=now,
    ))
    session.commit()


def _make_create(session):
    return CreateEquipmentSetUseCase(
        player_repository=PlayerRepository(session),
        equipment_repository=EquipmentRepository(session),
        equipment_set_repository=EquipmentSetRepository(session),
    )


def _make_delete(session):
    return DeleteEquipmentSetUseCase(
        player_repository=PlayerRepository(session),
        equipment_set_repository=EquipmentSetRepository(session),
    )


def _make_equip(session):
    return EquipSavedSetUseCase(
        player_repository=PlayerRepository(session),
        equipment_repository=EquipmentRepository(session),
        equipment_set_repository=EquipmentSetRepository(session),
        inventory_repository=InventoryRepository(session),
    )


def _make_unequip_all(session):
    return UnequipAllUseCase(
        player_repository=PlayerRepository(session),
        equipment_repository=EquipmentRepository(session),
    )


def test_create_set_persists_currently_equipped(session):
    pid = _create_player(session)
    h = _create_item(session, "iron_helmet", "helmet", "casque")
    p = _create_item(session, "iron_chest", "chest", "plastron")
    _equip_pre(session, pid, h, "casque")
    _equip_pre(session, pid, p, "plastron")

    result = _make_create(session).execute(
        discord_id=1, username="a", display_name="A", name="tank",
    )

    assert result.success is True
    assert result.pieces_saved == 2
    saved = EquipmentSetRepository(session).get_by_name(pid, "tank")
    assert saved is not None
    slots = sorted(it.slot for it in saved.items)
    assert slots == ["casque", "plastron"]


def test_create_set_refuses_empty_equipment(session):
    pid = _create_player(session)
    result = _make_create(session).execute(
        discord_id=1, username="a", display_name="A", name="empty",
    )
    assert result.success is False
    assert "Aucun équipement" in result.message


def test_create_set_refuses_duplicate_name(session):
    pid = _create_player(session)
    h = _create_item(session, "iron_helmet", "helmet", "casque")
    _equip_pre(session, pid, h, "casque")
    _make_create(session).execute(
        discord_id=1, username="a", display_name="A", name="dps",
    )
    second = _make_create(session).execute(
        discord_id=1, username="a", display_name="A", name="dps",
    )
    assert second.success is False
    assert "déjà un set" in second.message


def test_delete_set_removes_persisted(session):
    pid = _create_player(session)
    h = _create_item(session, "iron_helmet", "helmet", "casque")
    _equip_pre(session, pid, h, "casque")
    _make_create(session).execute(
        discord_id=1, username="a", display_name="A", name="todel",
    )

    result = _make_delete(session).execute(
        discord_id=1, username="a", display_name="A", name="todel",
    )
    assert result.success is True
    assert EquipmentSetRepository(session).get_by_name(pid, "todel") is None


def test_delete_unknown_set_returns_failure(session):
    pid = _create_player(session)
    result = _make_delete(session).execute(
        discord_id=1, username="a", display_name="A", name="ghost",
    )
    assert result.success is False
    assert "Aucun set" in result.message


def test_equip_set_swaps_correctly(session):
    pid = _create_player(session)
    h = _create_item(session, "iron_helmet", "helmet", "casque")
    p = _create_item(session, "iron_chest", "chest", "plastron")
    other = _create_item(session, "leather_cap", "helmet", "casque")
    _equip_pre(session, pid, other, "casque")  # casque déjà tenu par autre
    _give(session, pid, h, 1)  # iron_helmet en inventaire
    _give(session, pid, p, 1)  # iron_chest en inventaire

    # Crée un set "iron" en pré-équipant temporairement
    _equip_pre(session, pid, p, "plastron")  # plastron OK
    EquipmentRepository(session).unequip_slot(pid, "casque")
    _equip_pre(session, pid, h, "casque")
    _make_create(session).execute(
        discord_id=1, username="a", display_name="A", name="iron",
    )
    # Remet l'autre casque pour vérifier le swap
    EquipmentRepository(session).unequip_slot(pid, "casque")
    _equip_pre(session, pid, other, "casque")

    # Equipe le set sauvegardé
    result = _make_equip(session).execute(
        discord_id=1, username="a", display_name="A", name="iron",
    )
    assert result.success is True
    eq = EquipmentRepository(session).list_by_player_id(pid)
    by_slot = {e.slot: e.item_definition.code for e in eq}
    assert by_slot["casque"] == "iron_helmet"
    assert by_slot["plastron"] == "iron_chest"


def test_equip_set_fails_if_item_missing(session):
    pid = _create_player(session)
    h = _create_item(session, "iron_helmet", "helmet", "casque")
    _equip_pre(session, pid, h, "casque")
    _make_create(session).execute(
        discord_id=1, username="a", display_name="A", name="halfset",
    )

    # Le joueur perd l'item (vendu / tradé). On le retire.
    EquipmentRepository(session).unequip_slot(pid, "casque")
    # Il n'a plus iron_helmet en inventaire ni équipé.

    result = _make_equip(session).execute(
        discord_id=1, username="a", display_name="A", name="halfset",
    )
    assert result.success is False
    assert "Pièces manquantes" in result.message
    assert any("iron_helmet" in s.lower() or "Iron Helmet" in s for s in result.missing_items)


def test_unequip_all_clears_every_slot(session):
    pid = _create_player(session)
    h = _create_item(session, "iron_helmet", "helmet", "casque")
    p = _create_item(session, "iron_chest", "chest", "plastron")
    _equip_pre(session, pid, h, "casque")
    _equip_pre(session, pid, p, "plastron")

    result = _make_unequip_all(session).execute(
        discord_id=1, username="a", display_name="A",
    )
    assert result.success is True
    assert sorted(result.slots_cleared) == ["casque", "plastron"]
    assert EquipmentRepository(session).list_by_player_id(pid) == []


def test_unequip_all_fails_when_nothing_equipped(session):
    pid = _create_player(session)
    result = _make_unequip_all(session).execute(
        discord_id=1, username="a", display_name="A",
    )
    assert result.success is False
