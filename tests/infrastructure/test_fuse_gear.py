"""Fusion de rareté : 2 copies identiques + or + matériaux de famille → +1 rareté."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application.use_cases.fuse_gear import FuseGearUseCase
from app.domain.services.artisan_service import ArtisanService
from app.infrastructure.artisans import artisan_loader
from app.infrastructure.db.base import Base
from app.infrastructure.db.models.item_model import ItemDefinitionModel
from app.infrastructure.db.models.mob_model import MobDefinitionModel
from app.infrastructure.db.models.resource_model import PlayerResourceModel
from app.infrastructure.db.repositories.equipment_repository import EquipmentRepository
from app.infrastructure.db.repositories.gear_repository import GearRepository
from app.infrastructure.db.repositories.inventory_repository import InventoryRepository
from app.infrastructure.db.repositories.player_repository import PlayerRepository

NOW = datetime.now(UTC)


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def _item(session, code, category, slot_type, stats=None):
    m = ItemDefinitionModel(
        code=code, name=code.title(), description="", category=category, rarity="common",
        stackable=category == "resource", max_stack=None, sell_price=0, buy_price=None,
        icon=None, stat_bonuses_json=stats, equipment_slot=slot_type,
        requires_two_hands=False, family="", created_at=NOW, updated_at=NOW,
    )
    session.add(m); session.commit()
    return m


def _world(session, gold=100_000, teeth=500):
    sword = _item(session, "surin_dentele", "arme", "arme", {"attack_pct": 8})
    tooth = _item(session, "dent_de_gobelin", "resource", None)
    session.add(MobDefinitionModel(
        code="gobelin", name="Gobelin", description="", image_name="", family="gobelin",
        max_hp=10, current_hp=10, attack=1, defense=1, speed=5, xp_reward=1, gold_reward=1,
        spawn_weight=1, loot_table_json=[], crit_chance=0, crit_damage=100, dodge=0,
        hp_regeneration=0, gear_item_code="surin_dentele", created_at=NOW, updated_at=NOW,
    ))
    session.commit()
    pid = PlayerRepository(session).get_or_create_by_discord_id(1, "u", "U").player.id
    session.get(PlayerResourceModel, pid).gold = gold
    session.commit()
    if teeth:
        InventoryRepository(session).add_item(pid, tooth.id, teeth)
    return pid, sword


def _use_case(session):
    return FuseGearUseCase(session, ArtisanService(artisan_loader.load_pricing()))


def _forgeron():
    return artisan_loader.get_artisan("forgeron")


def test_deux_communs_donnent_un_peu_commun(session):
    pid, sword = _world(session)
    gear = GearRepository(session)
    gear.add(pid, sword.id, "common")
    gear.add(pid, sword.id, "common", forge_level=3)
    res = _use_case(session).fuse(_forgeron(), pid, "surin_dentele", "common")
    assert res.success and res.new_rarity == "uncommon"
    owned = gear.list_owned(pid)
    assert [(g.rarity, g.forge_level, g.source) for g in owned] == [("uncommon", 3, "fusion")]
    assert session.get(PlayerResourceModel, pid).gold == 100_000 - 200
    teeth = [i for i in InventoryRepository(session).list_by_player_id(pid)
             if i.item_definition.code == "dent_de_gobelin"][0]
    assert teeth.quantity == 500 - 5


def test_la_copie_portee_garde_sa_place(session):
    pid, sword = _world(session)
    gear = GearRepository(session)
    worn = gear.add(pid, sword.id, "rare")
    gear.add(pid, sword.id, "rare")
    EquipmentRepository(session).equip_gear(pid, worn.id, "arme_2")
    assert _use_case(session).fuse(_forgeron(), pid, "surin_dentele", "rare").success
    equipped = EquipmentRepository(session).list_by_player_id(pid)
    assert [(e.slot, e.rarity) for e in equipped] == [("arme_2", "epic")]


@pytest.mark.parametrize("copies, gold, teeth, reason", [
    (1, 100_000, 500, "2 copies"),
    (2, 100, 500, "or"),
    (2, 100_000, 2, "Dent"),
])
def test_ce_qui_bloque_la_fusion(session, copies, gold, teeth, reason):
    pid, sword = _world(session, gold=gold, teeth=teeth)
    for _ in range(copies):
        GearRepository(session).add(pid, sword.id, "common")
    res = _use_case(session).fuse(_forgeron(), pid, "surin_dentele", "common")
    assert not res.success and reason in res.message
    assert len(GearRepository(session).list_owned(pid)) == copies  # rien n'a bougé


def test_legendaire_et_mythique_ne_fusionnent_pas(session):
    pid, sword = _world(session)
    for rarity in ("legendary", "legendary", "mythic", "mythic"):
        GearRepository(session).add(pid, sword.id, rarity)
    for rarity in ("legendary", "mythic"):
        assert not _use_case(session).fuse(_forgeron(), pid, "surin_dentele", rarity).success


def test_borak_fusionne_toutes_les_pieces_accessoires_compris():
    """Depuis le 26/10/2026, Borak fait toutes les fusions (Elna est alchimiste)."""
    from app.shared.enums import EQUIPABLE_CATEGORIES

    assert [a.code for a in artisan_loader.list_artisans()] == ["forgeron"]
    for category in EQUIPABLE_CATEGORIES:
        assert artisan_loader.artisan_for_category(str(getattr(category, "value", category))).code == "forgeron"


def test_la_fusion_fait_monter_la_maitrise(session):
    from app.infrastructure.db.repositories.work_order_repository import WorkOrderRepository

    pid, sword = _world(session)
    for _ in range(2):
        GearRepository(session).add(pid, sword.id, "common")
    _use_case(session).fuse(_forgeron(), pid, "surin_dentele", "common")
    assert WorkOrderRepository(session).orders_completed(pid, "forgeron") == 1
