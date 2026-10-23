"""Drop d'équipement à la mort d'un monstre (équipement v2)."""

import random
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application.services.encounter_service import EncounterService
from app.infrastructure.db.base import Base
from app.infrastructure.db.models.item_model import ItemDefinitionModel
from app.infrastructure.db.repositories.equipment_repository import EquipmentRepository
from app.infrastructure.db.repositories.gear_repository import GearRepository
from app.infrastructure.db.repositories.player_repository import PlayerRepository

NOW = datetime.now(UTC)


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def _item(session, code, passive=""):
    m = ItemDefinitionModel(
        code=code, name=code.title(), description="", category="accessoire", rarity="common",
        stackable=False, max_stack=None, sell_price=0, buy_price=None, icon=None,
        stat_bonuses_json={"dodge": 1}, equipment_slot="accessoire", requires_two_hands=False,
        family="", passive=passive, created_at=NOW, updated_at=NOW,
    )
    session.add(m); session.commit()
    return m


class _Rng:
    """Tirage imposé : random() renvoie la valeur donnée."""
    def __init__(self, value):
        self.value = value

    def random(self):
        return self.value


def test_un_monstre_lache_sa_piece_dans_la_rarete_tiree(session):
    _item(session, "surin_dentele")
    pid = PlayerRepository(session).get_or_create_by_discord_id(1, "u", "U").player.id
    mob = SimpleNamespace(gear_item_code="surin_dentele")
    # 0,0 % → la tranche la plus rare : mythique
    assert EncounterService._roll_gear_drop(session, pid, mob, _Rng(0.0)) == [("Surin_Dentele", "mythic")]
    # 99 % → rien
    assert EncounterService._roll_gear_drop(session, pid, mob, _Rng(0.99)) == []
    owned = GearRepository(session).list_owned(pid)
    assert [(g.rarity, g.source) for g in owned] == [("mythic", "drop")]


def test_monstre_sans_piece(session):
    pid = PlayerRepository(session).get_or_create_by_discord_id(1, "u", "U").player.id
    assert EncounterService._roll_gear_drop(session, pid, SimpleNamespace(gear_item_code=""), _Rng(0.0)) == []


def test_le_passif_trouvaille_augmente_les_chances(session):
    perle = _item(session, "perle_de_gelee", passive="lucky_find")
    _item(session, "surin_dentele")
    pid = PlayerRepository(session).get_or_create_by_discord_id(1, "u", "U").player.id
    mob = SimpleNamespace(gear_item_code="surin_dentele")
    # Juste au-dessus du total des taux (9,534 %) : rien sans le passif…
    roll = 0.0960
    assert EncounterService._roll_gear_drop(session, pid, mob, _Rng(roll)) == []
    # … une pièce commune avec la Perle de gelée ÉPIQUE portée (+10 %).
    gear = GearRepository(session).add(pid, perle.id, "epic")
    EquipmentRepository(session).equip_gear(pid, gear.id, "accessoire_1")
    assert EncounterService._roll_gear_drop(session, pid, mob, _Rng(roll)) == [("Surin_Dentele", "common")]


def test_le_passif_ne_compte_pas_avant_l_epique(session):
    perle = _item(session, "perle_de_gelee", passive="lucky_find")
    _item(session, "surin_dentele")
    pid = PlayerRepository(session).get_or_create_by_discord_id(1, "u", "U").player.id
    gear = GearRepository(session).add(pid, perle.id, "rare")
    EquipmentRepository(session).equip_gear(pid, gear.id, "accessoire_1")
    mob = SimpleNamespace(gear_item_code="surin_dentele")
    assert EncounterService._roll_gear_drop(session, pid, mob, _Rng(0.0960)) == []
