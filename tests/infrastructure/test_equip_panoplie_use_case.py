"""Tests d'intégration de EquipPanoplieUseCase.

Couvre :
- échec quand pondéré < 12
- succès 12 items 1-main → tous les slots couverts
- succès avec 2-mains qui compte pour 2 (main_gauche reste vide)
- conserve les pièces de la bonne famille déjà équipées
- déséquipe les pièces hors-famille présentes dans les slots cibles
- panoplie incomplète sur 1 slot → échec avec missing_slots
"""

from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application.use_cases.equip_panoplie import EquipPanoplieUseCase
from app.infrastructure.db.base import Base

# Modèles pour create_all
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

from app.infrastructure.db.repositories.equipment_repository import EquipmentRepository
from app.infrastructure.db.repositories.inventory_repository import InventoryRepository
from app.infrastructure.db.repositories.player_repository import PlayerRepository


_TWELVE_SLOTS = [
    "casque", "plastron", "jambieres", "bottes",
    "main_droite", "main_gauche",
    "collier", "bracelet", "bague",
    "ceinture", "cape", "boucle_oreille",
]


_FAKE_SETS = {
    "iron": {"name": "Fer", "icon": "🛡️", "tiers": []},
    "slime": {"name": "Slime", "icon": "🟢", "tiers": []},
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


def _create_player(session, discord_id: int = 1) -> int:
    now = datetime.now(UTC)
    player = PlayerModel(
        discord_id=discord_id,
        username="alpha", display_name="Alpha",
        created_at=now, updated_at=now, last_seen_at=now,
    )
    session.add(player)
    session.flush()
    session.add_all([
        PlayerProgressionModel(
            player_id=player.id, level=1, xp=0, skill_points=0,
            created_at=now, updated_at=now,
        ),
        PlayerResourceModel(
            player_id=player.id, gold=0,
            created_at=now, updated_at=now,
        ),
    ])
    session.commit()
    return player.id


def _create_item(
    session, code, category, equipment_slot, family,
    requires_two_hands=False,
) -> int:
    now = datetime.now(UTC)
    item = ItemDefinitionModel(
        code=code, name=code, description="",
        category=category, rarity="common",
        stackable=False, max_stack=None,
        sell_price=0, buy_price=None, icon=None,
        stat_bonuses_json=None,
        equipment_slot=equipment_slot,
        requires_two_hands=requires_two_hands,
        family=family,
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


_SLOT_TO_CATEGORY = {
    "casque": "helmet", "plastron": "chest", "jambieres": "legs",
    "bottes": "boots", "main_droite": "weapon", "main_gauche": "shield",
    "collier": "necklace", "bracelet": "bracelet", "bague": "ring",
    "ceinture": "belt", "cape": "cape", "boucle_oreille": "earring",
}


def _setup_full_panoplie_in_inventory(session, pid, family):
    """Donne 1 item iron par slot (12 items)."""
    ids = {}
    for slot in _TWELVE_SLOTS:
        cat = _SLOT_TO_CATEGORY[slot]
        item_id = _create_item(
            session, f"{family}_{slot}", cat, slot, family,
        )
        _give(session, pid, item_id)
        ids[slot] = item_id
    return ids


def _make_use_case(session):
    return EquipPanoplieUseCase(
        player_repository=PlayerRepository(session),
        inventory_repository=InventoryRepository(session),
        equipment_repository=EquipmentRepository(session),
    )


@patch(
    "app.application.use_cases.equip_panoplie.list_set_definitions",
    return_value=_FAKE_SETS,
)
def test_full_panoplie_equips_all_12_slots(_, session):
    pid = _create_player(session)
    _setup_full_panoplie_in_inventory(session, pid, "iron")

    result = _make_use_case(session).execute(
        discord_id=1, username="alpha", display_name="Alpha", family="iron",
    )

    assert result.success is True
    equipped = EquipmentRepository(session).list_by_player_id(pid)
    assert len(equipped) == 12
    assert all(e.item_definition.family == "iron" for e in equipped)


@patch(
    "app.application.use_cases.equip_panoplie.list_set_definitions",
    return_value=_FAKE_SETS,
)
def test_incomplete_panoplie_fails(_, session):
    pid = _create_player(session)
    # Seulement 5 items sur 12
    for slot in _TWELVE_SLOTS[:5]:
        cat = _SLOT_TO_CATEGORY[slot]
        item_id = _create_item(
            session, f"iron_{slot}", cat, slot, "iron",
        )
        _give(session, pid, item_id)

    result = _make_use_case(session).execute(
        discord_id=1, username="alpha", display_name="Alpha", family="iron",
    )

    assert result.success is False
    assert "5/12" in result.message
    # Rien d'équipé
    assert EquipmentRepository(session).list_by_player_id(pid) == []


@patch(
    "app.application.use_cases.equip_panoplie.list_set_definitions",
    return_value=_FAKE_SETS,
)
def test_two_handed_weapon_counts_as_two(_, session):
    """11 items en inventaire dont 1 arme 2-mains → 12/12 valide.
    main_gauche reste vide après equip."""
    pid = _create_player(session)
    # 10 items hors mains
    for slot in _TWELVE_SLOTS:
        if slot in ("main_droite", "main_gauche"):
            continue
        cat = _SLOT_TO_CATEGORY[slot]
        item_id = _create_item(
            session, f"iron_{slot}", cat, slot, "iron",
        )
        _give(session, pid, item_id)
    # 1 arme 2-mains
    weapon_id = _create_item(
        session, "iron_2h", "weapon", "main_droite", "iron",
        requires_two_hands=True,
    )
    _give(session, pid, weapon_id)

    result = _make_use_case(session).execute(
        discord_id=1, username="alpha", display_name="Alpha", family="iron",
    )

    assert result.success is True
    equipped = EquipmentRepository(session).list_by_player_id(pid)
    # 11 records (main_gauche reste vide à cause du 2-mains)
    assert len(equipped) == 11
    md = next(e for e in equipped if e.slot == "main_droite")
    assert md.item_definition.code == "iron_2h"
    assert all(e.slot != "main_gauche" for e in equipped)


@patch(
    "app.application.use_cases.equip_panoplie.list_set_definitions",
    return_value=_FAKE_SETS,
)
def test_keeps_already_equipped_family_pieces(_, session):
    pid = _create_player(session)
    ids = _setup_full_panoplie_in_inventory(session, pid, "iron")
    # Pré-équipe 3 pièces (casque, bague, cape)
    for slot in ("casque", "bague", "cape"):
        _equip_pre(session, pid, ids[slot], slot)

    result = _make_use_case(session).execute(
        discord_id=1, username="alpha", display_name="Alpha", family="iron",
    )

    assert result.success is True
    assert result.kept_pieces == 3
    # Les 9 autres ont été équipés (changes)
    assert len(result.equipped_changes) == 9


@patch(
    "app.application.use_cases.equip_panoplie.list_set_definitions",
    return_value=_FAKE_SETS,
)
def test_replaces_off_family_equipped_pieces(_, session):
    """Un slot tenu par un item d'une autre famille est correctement remplacé."""
    pid = _create_player(session)
    iron_ids = _setup_full_panoplie_in_inventory(session, pid, "iron")
    # Pré-équipe un casque slime (autre famille) sur le slot casque
    slime_helm = _create_item(
        session, "slime_casque", "helmet", "casque", "slime",
    )
    _equip_pre(session, pid, slime_helm, "casque")

    result = _make_use_case(session).execute(
        discord_id=1, username="alpha", display_name="Alpha", family="iron",
    )

    assert result.success is True
    casque = EquipmentRepository(session).get_slot(pid, "casque")
    assert casque.item_definition.code == "iron_casque"


@patch(
    "app.application.use_cases.equip_panoplie.list_set_definitions",
    return_value=_FAKE_SETS,
)
def test_unknown_family_fails(_, session):
    pid = _create_player(session)
    result = _make_use_case(session).execute(
        discord_id=1, username="alpha", display_name="Alpha",
        family="unknown_family",
    )
    assert result.success is False
    assert "introuvable" in result.message
