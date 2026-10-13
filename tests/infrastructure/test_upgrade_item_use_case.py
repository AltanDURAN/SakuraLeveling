"""Fusion d'équipement chez l'artisan, en base.

Règles verrouillées :
  • une fusion consomme UNE copie et de l'or, et monte la pièce d'un niveau ;
  • on ne peut pas fusionner la copie qu'on porte (ni l'une des deux si on
    porte deux fois la même arme) ;
  • le prix monte avec le niveau visé ;
  • +10 est un plafond ;
  • chaque artisan n'améliore que ce qu'il fabrique.
"""

import pytest

from app.application.use_cases.upgrade_item import UpgradeItemUseCase
from app.domain.entities.artisan import PricingRules
from app.domain.services.artisan_service import ArtisanService
from app.domain.services.item_upgrade_service import MAX_ITEM_LEVEL
from app.infrastructure.db.models.equipment_model import PlayerEquipmentItemModel  # noqa: F401
from app.infrastructure.db.models.player_item_level_model import PlayerItemLevelModel  # noqa: F401
from app.infrastructure.db.repositories.equipment_repository import EquipmentRepository
from app.infrastructure.db.repositories.inventory_repository import InventoryRepository
from app.infrastructure.db.repositories.player_item_level_repository import (
    PlayerItemLevelRepository,
)
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.repositories.work_order_repository import WorkOrderRepository
from tests.infrastructure.test_artisan_work_use_case import (  # noqa: F401
    _forgeron,
    _gold,
    _item,
    _qty,
    session,
)


def _uc(session) -> UpgradeItemUseCase:
    return UpgradeItemUseCase(
        player_repository=PlayerRepository(session),
        inventory_repository=InventoryRepository(session),
        equipment_repository=EquipmentRepository(session),
        item_level_repository=PlayerItemLevelRepository(session),
        work_order_repository=WorkOrderRepository(session),
        artisan_service=ArtisanService(PricingRules()),
    )


@pytest.fixture()
def player(session):
    profile = PlayerRepository(session).get_or_create_by_discord_id(
        discord_id=7, username="u", display_name="U",
    )
    pid = profile.player.id
    PlayerRepository(session).add_gold(pid, 100_000)
    sword = _item(session, "epee", category="arme", bonuses={"attack_pct": 20})
    ring = _item(session, "anneau", category="accessoire", bonuses={"crit_chance": 3})
    session.commit()
    return {"pid": pid, "sword": sword, "ring": ring}


def _level(session, pid, item_id):
    return PlayerItemLevelRepository(session).get_level(pid, item_id)


def test_fusionner_consomme_une_copie_et_de_l_or(session, player):
    pid, sword = player["pid"], player["sword"]
    InventoryRepository(session).add_item(pid, sword.id, 2)
    before = _gold(session, pid)
    uc = _uc(session)

    preview = uc.preview(_forgeron(), pid, "epee")
    assert preview.can_upgrade
    assert preview.bonuses_next == {"attack_pct": 22}

    result = uc.upgrade(_forgeron(), pid, "epee")
    session.commit()

    assert result.success and result.new_level == 1
    assert _qty(session, pid, "epee") == 1
    assert _gold(session, pid) == before - preview.gold_cost
    assert _level(session, pid, sword.id) == 1


def test_une_seule_copie_ne_suffit_pas(session, player):
    pid, sword = player["pid"], player["sword"]
    InventoryRepository(session).add_item(pid, sword.id, 1)
    result = _uc(session).upgrade(_forgeron(), pid, "epee")
    assert not result.success
    assert _qty(session, pid, "epee") == 1


def test_on_ne_sacrifie_pas_une_piece_portee(session, player):
    """Deux épées identiques portées : il en faut une TROISIÈME pour fusionner."""
    pid, sword = player["pid"], player["sword"]
    InventoryRepository(session).add_item(pid, sword.id, 2)
    equipment = EquipmentRepository(session)
    equipment.equip_item(pid, sword.id, "arme_1")
    equipment.equip_item(pid, sword.id, "arme_2")
    session.commit()

    preview = _uc(session).preview(_forgeron(), pid, "epee")
    assert preview.required == 3
    assert not preview.can_upgrade
    assert not _uc(session).upgrade(_forgeron(), pid, "epee").success


def test_le_prix_monte_avec_le_niveau(session, player):
    pid, sword = player["pid"], player["sword"]
    InventoryRepository(session).add_item(pid, sword.id, 4)
    uc = _uc(session)
    first = uc.preview(_forgeron(), pid, "epee").gold_cost
    uc.upgrade(_forgeron(), pid, "epee")
    session.commit()
    second = uc.preview(_forgeron(), pid, "epee").gold_cost
    assert second == pytest.approx(first * 2, abs=1)


def test_plus_dix_est_un_plafond(session, player):
    pid, sword = player["pid"], player["sword"]
    InventoryRepository(session).add_item(pid, sword.id, 5)
    levels = PlayerItemLevelRepository(session)
    for _ in range(MAX_ITEM_LEVEL):
        levels.increment(pid, sword.id, MAX_ITEM_LEVEL)
    session.commit()

    preview = _uc(session).preview(_forgeron(), pid, "epee")
    assert preview.maxed and not preview.can_upgrade
    assert not _uc(session).upgrade(_forgeron(), pid, "epee").success
    assert _qty(session, pid, "epee") == 5


def test_pas_assez_d_or(session, player):
    pid, sword = player["pid"], player["sword"]
    InventoryRepository(session).add_item(pid, sword.id, 2)
    PlayerRepository(session).set_gold(pid, 0)
    session.commit()
    result = _uc(session).upgrade(_forgeron(), pid, "epee")
    assert not result.success
    assert _qty(session, pid, "epee") == 2


def test_chaque_artisan_n_ameliore_que_ce_qu_il_fabrique(session, player):
    """Le forgeron ne touche pas aux accessoires : c'est le travail d'Elna."""
    pid, ring = player["pid"], player["ring"]
    InventoryRepository(session).add_item(pid, ring.id, 3)
    uc = _uc(session)
    assert uc.preview(_forgeron(), pid, "anneau") is None
    assert [c.item_code for c in uc.candidates(_forgeron(), pid)] == []
