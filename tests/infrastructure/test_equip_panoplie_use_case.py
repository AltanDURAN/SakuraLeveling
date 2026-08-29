"""Tests de `/equiper_panoplie` — système simplifié.

Une panoplie ne couvre plus que 4 emplacements : tête, corps et les deux
mains. Les anciennes options (double_armes, arme_lourde…) ont disparu : le use
case choisit désormais tout seul la meilleure configuration selon ce que le joueur
possède, en privilégiant deux pièces à 1 main (4/4) sinon une 2-mains.
"""

from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application.use_cases.equip_panoplie import EquipPanoplieUseCase
from app.infrastructure.db.base import Base
from app.infrastructure.db.models.player_model import PlayerModel  # noqa: F401
from app.infrastructure.db.models.progression_model import PlayerProgressionModel  # noqa: F401
from app.infrastructure.db.models.resource_model import PlayerResourceModel  # noqa: F401
from app.infrastructure.db.models.item_model import ItemDefinitionModel
from app.infrastructure.db.models.inventory_model import PlayerInventoryItemModel  # noqa: F401
from app.infrastructure.db.models.equipment_model import PlayerEquipmentItemModel  # noqa: F401
from app.infrastructure.db.repositories.equipment_repository import EquipmentRepository
from app.infrastructure.db.repositories.inventory_repository import InventoryRepository
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.shared.enums import EquipmentSlot

_DEFS = {"iron": {"name": "Acier", "icon": "🛡️",
                  "tiers": [{"min_pieces": 2, "type": "defense_flat", "value": 3},
                            {"min_pieces": 4, "type": "defense_flat", "value": 8}]}}


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


def _item(session, code, category, slot_type, family="iron", two_handed=False):
    now = datetime.now(UTC)
    m = ItemDefinitionModel(
        code=code, name=code, description="", category=category, rarity="common",
        stackable=False, max_stack=None, sell_price=0, buy_price=None, icon=None,
        stat_bonuses_json=None, equipment_slot=slot_type,
        requires_two_hands=two_handed, family=family,
        created_at=now, updated_at=now,
    )
    session.add(m); session.commit()
    return m


def _setup(session, items):
    player = PlayerRepository(session).get_or_create_by_discord_id(
        discord_id=1, username="u", display_name="U",
    )
    pid = player.player.id
    for it in items:
        InventoryRepository(session).add_item(pid, it.id, 1)
    session.commit()
    use_case = EquipPanoplieUseCase(
        player_repository=PlayerRepository(session),
        inventory_repository=InventoryRepository(session),
        equipment_repository=EquipmentRepository(session),
    )
    return pid, use_case


def _run(use_case, family="iron"):
    return use_case.execute(discord_id=1, username="u", display_name="U",
                            family=family)


def _worn(session, pid):
    return {e.slot: e.item_definition.code
            for e in EquipmentRepository(session).list_by_player_id(pid)}


@patch("app.application.use_cases.equip_panoplie.get_set_definition",
       side_effect=lambda f: _DEFS.get(f))
def test_panoplie_complete_avec_deux_armes_une_main(_, session):
    pid, uc = _setup(session, [
        _item(session, "casque_fer", "tete", "tete"),
        _item(session, "armure_fer", "corps", "corps"),
        _item(session, "epee_fer", "arme", "arme"),
        _item(session, "ecu_fer", "bouclier", "arme"),
    ])
    res = _run(uc)
    assert res.success and "4/4" in res.message
    worn = _worn(session, pid)
    assert set(worn) == {EquipmentSlot.TETE.value, EquipmentSlot.CORPS.value,
                         EquipmentSlot.ARME_1.value, EquipmentSlot.ARME_2.value}


@patch("app.application.use_cases.equip_panoplie.get_set_definition",
       side_effect=lambda f: _DEFS.get(f))
def test_une_deux_mains_occupe_les_deux_emplacements(_, session):
    pid, uc = _setup(session, [
        _item(session, "casque_fer", "tete", "tete"),
        _item(session, "armure_fer", "corps", "corps"),
        _item(session, "espadon_fer", "arme", "arme", two_handed=True),
    ])
    res = _run(uc)
    assert res.success
    worn = _worn(session, pid)
    assert worn[EquipmentSlot.ARME_1.value] == "espadon_fer"
    assert EquipmentSlot.ARME_2.value not in worn


@patch("app.application.use_cases.equip_panoplie.get_set_definition",
       side_effect=lambda f: _DEFS.get(f))
def test_deux_armes_une_main_preferees_a_la_deux_mains(_, session):
    """À choisir, deux pièces à 1 main valent 4/4 — on les privilégie."""
    pid, uc = _setup(session, [
        _item(session, "epee_fer", "arme", "arme"),
        _item(session, "dague_fer", "arme", "arme"),
        _item(session, "espadon_fer", "arme", "arme", two_handed=True),
    ])
    _run(uc)
    worn = _worn(session, pid)
    assert set(worn.values()) == {"epee_fer", "dague_fer"}


@patch("app.application.use_cases.equip_panoplie.get_set_definition",
       side_effect=lambda f: _DEFS.get(f))
def test_pieces_manquantes_signalees(_, session):
    _, uc = _setup(session, [_item(session, "casque_fer", "tete", "tete")])
    res = _run(uc)
    assert res.success
    assert EquipmentSlot.CORPS.value in res.missing_slots
    assert "1/4" in res.message


@patch("app.application.use_cases.equip_panoplie.get_set_definition",
       side_effect=lambda f: _DEFS.get(f))
def test_remplace_les_pieces_hors_famille(_, session):
    pid, uc = _setup(session, [
        _item(session, "casque_fer", "tete", "tete"),
        _item(session, "casque_bois", "tete", "tete", family="wood"),
    ])
    EquipmentRepository(session).equip_item(
        pid, _item(session, "vieux_casque", "tete", "tete", family="wood").id,
        EquipmentSlot.TETE.value,
    )
    _run(uc)
    assert _worn(session, pid)[EquipmentSlot.TETE.value] == "casque_fer"


@patch("app.application.use_cases.equip_panoplie.get_set_definition",
       side_effect=lambda f: _DEFS.get(f))
def test_aucune_piece_possedee_echoue(_, session):
    _, uc = _setup(session, [])
    res = _run(uc)
    assert res.success is False and "aucune pièce" in res.message.lower()


@patch("app.application.use_cases.equip_panoplie.get_set_definition",
       side_effect=lambda f: _DEFS.get(f))
def test_famille_inconnue_echoue(_, session):
    _, uc = _setup(session, [])
    res = _run(uc, family="inexistante")
    assert res.success is False and "introuvable" in res.message
