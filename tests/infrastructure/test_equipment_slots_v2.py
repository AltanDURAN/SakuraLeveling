"""Système d'équipement SIMPLIFIÉ : 7 emplacements, types d'items.

Vérifie les règles qui remplacent l'ancien système main droite / main gauche :
  • un accessoire se pose tout seul dans le premier emplacement libre (×3) ;
  • armes et boucliers partagent les 2 mains, sans notion de main dominante ;
  • une pièce à 2 mains occupe les DEUX emplacements et verrouille l'autre ;
  • on ne peut pas porter deux fois le même item avec un seul exemplaire.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application.use_cases.equip_item import EquipItemUseCase
from app.infrastructure.db.base import Base
from app.infrastructure.db.models.player_model import PlayerModel  # noqa: F401
from app.infrastructure.db.models.progression_model import PlayerProgressionModel  # noqa: F401
from app.infrastructure.db.models.resource_model import PlayerResourceModel  # noqa: F401
from app.infrastructure.db.models.item_model import ItemDefinitionModel
from app.infrastructure.db.models.inventory_model import PlayerInventoryItemModel  # noqa: F401
from app.infrastructure.db.models.equipment_model import PlayerEquipmentItemModel  # noqa: F401
from app.infrastructure.db.repositories.equipment_repository import EquipmentRepository
from app.infrastructure.db.repositories.inventory_repository import InventoryRepository
from app.infrastructure.db.repositories.item_repository import ItemRepository
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.shared.enums import EquipmentSlot


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


def _item(session, code, category, slot_type, two_handed=False):
    now = datetime.now(UTC)
    m = ItemDefinitionModel(
        code=code, name=code, description="", category=category, rarity="common",
        stackable=False, max_stack=None, sell_price=0, buy_price=None, icon=None,
        stat_bonuses_json={"attack": 1}, equipment_slot=slot_type,
        requires_two_hands=two_handed, family="", created_at=now, updated_at=now,
    )
    session.add(m); session.commit()
    return m


def _setup(session):
    player = PlayerRepository(session).get_or_create_by_discord_id(
        discord_id=1, username="u", display_name="U",
    )
    use_case = EquipItemUseCase(
        player_repository=PlayerRepository(session),
        inventory_repository=InventoryRepository(session),
        equipment_repository=EquipmentRepository(session),
    )
    return player.player.id, use_case


def _give(session, player_id, item, qty=1):
    InventoryRepository(session).add_item(player_id, item.id, qty)
    session.commit()


def _equip(use_case, code, slot=None):
    return use_case.execute(discord_id=1, username="u", display_name="U",
                            item_code=code, slot=slot)


def _worn(session, player_id) -> dict[str, str]:
    return {
        e.slot: e.item_definition.code
        for e in EquipmentRepository(session).list_by_player_id(player_id)
    }


# ---------------------------------------------------------------- accessoires

def test_accessoires_remplissent_les_trois_emplacements(session):
    pid, uc = _setup(session)
    for i in range(3):
        it = _item(session, f"anneau_{i}", "accessoire", "accessoire")
        _give(session, pid, it)
        assert _equip(uc, f"anneau_{i}").success
    worn = _worn(session, pid)
    assert set(worn) == {
        EquipmentSlot.ACCESSOIRE_1.value,
        EquipmentSlot.ACCESSOIRE_2.value,
        EquipmentSlot.ACCESSOIRE_3.value,
    }


def test_quatrieme_accessoire_remplace_le_premier(session):
    pid, uc = _setup(session)
    for i in range(4):
        it = _item(session, f"bijou_{i}", "accessoire", "accessoire")
        _give(session, pid, it)
        _equip(uc, f"bijou_{i}")
    worn = _worn(session, pid)
    assert len(worn) == 3
    assert worn[EquipmentSlot.ACCESSOIRE_1.value] == "bijou_3"


# ---------------------------------------------------------------- armes

def test_deux_armes_une_main_cohabitent(session):
    pid, uc = _setup(session)
    for code in ("epee", "dague"):
        _give(session, pid, _item(session, code, "arme", "arme"))
        assert _equip(uc, code).success
    worn = _worn(session, pid)
    assert worn == {EquipmentSlot.ARME_1.value: "epee",
                    EquipmentSlot.ARME_2.value: "dague"}


def test_arme_et_bouclier_partagent_les_mains(session):
    """Plus de slot dédié au bouclier : il occupe une main comme une arme."""
    pid, uc = _setup(session)
    _give(session, pid, _item(session, "epee", "arme", "arme"))
    _give(session, pid, _item(session, "ecu", "bouclier", "arme"))
    assert _equip(uc, "epee").success
    assert _equip(uc, "ecu").success
    assert set(_worn(session, pid).values()) == {"epee", "ecu"}


def test_deux_mains_occupe_les_deux_emplacements(session):
    pid, uc = _setup(session)
    _give(session, pid, _item(session, "espadon", "arme", "arme", two_handed=True))
    res = _equip(uc, "espadon")
    assert res.success
    assert set(res.slots_equipped) == {EquipmentSlot.ARME_1.value,
                                       EquipmentSlot.ARME_2.value}
    worn = _worn(session, pid)
    assert worn == {EquipmentSlot.ARME_1.value: "espadon"}


def test_deux_mains_remplace_les_deux_armes_portees(session):
    pid, uc = _setup(session)
    for code in ("epee", "dague"):
        _give(session, pid, _item(session, code, "arme", "arme"))
        _equip(uc, code)
    _give(session, pid, _item(session, "espadon", "arme", "arme", two_handed=True))
    res = _equip(uc, "espadon")
    assert res.success
    assert sorted(res.unequipped_items) == ["dague", "epee"]
    assert _worn(session, pid) == {EquipmentSlot.ARME_1.value: "espadon"}


def test_arme_une_main_remplace_la_deux_mains(session):
    pid, uc = _setup(session)
    _give(session, pid, _item(session, "espadon", "arme", "arme", two_handed=True))
    _equip(uc, "espadon")
    _give(session, pid, _item(session, "epee", "arme", "arme"))
    res = _equip(uc, "epee")
    assert res.success and "espadon" in res.unequipped_items
    assert _worn(session, pid) == {EquipmentSlot.ARME_1.value: "epee"}


def test_meme_item_deux_fois_exige_deux_exemplaires(session):
    pid, uc = _setup(session)
    it = _item(session, "dague", "arme", "arme")
    _give(session, pid, it, qty=1)
    assert _equip(uc, "dague").success
    refus = _equip(uc, "dague")
    assert refus.success is False and "second exemplaire" in refus.message


def test_meme_item_deux_fois_ok_avec_deux_exemplaires(session):
    pid, uc = _setup(session)
    it = _item(session, "dague", "arme", "arme")
    _give(session, pid, it, qty=2)
    assert _equip(uc, "dague").success
    assert _equip(uc, "dague").success
    assert list(_worn(session, pid).values()) == ["dague", "dague"]


# ---------------------------------------------------------------- tête / corps

def test_tete_et_corps_ont_un_seul_emplacement(session):
    pid, uc = _setup(session)
    _give(session, pid, _item(session, "heaume", "tete", "tete"))
    _give(session, pid, _item(session, "armure", "corps", "corps"))
    _equip(uc, "heaume"); _equip(uc, "armure")
    worn = _worn(session, pid)
    assert worn == {EquipmentSlot.TETE.value: "heaume",
                    EquipmentSlot.CORPS.value: "armure"}


def test_emplacement_incompatible_refuse(session):
    pid, uc = _setup(session)
    _give(session, pid, _item(session, "heaume", "tete", "tete"))
    refus = _equip(uc, "heaume", slot=EquipmentSlot.ARME_1.value)
    assert refus.success is False
    assert "ne peut pas aller" in refus.message


def test_item_non_equipable_refuse(session):
    pid, uc = _setup(session)
    _give(session, pid, _item(session, "bois", "resource", None))
    refus = _equip(uc, "bois")
    assert refus.success is False and "pas équipable" in refus.message


def test_item_absent_de_inventaire_refuse(session):
    _, uc = _setup(session)
    refus = _equip(uc, "fantome")
    assert refus.success is False and "inventaire" in refus.message
