"""Le planificateur d'emplacement partagé entre `/equiper` et son preview.

Ces tests verrouillent la règle qui avait divergé : le preview calculait sa
propre cible en IGNORANT le cas des armes à 2 mains, donc il annonçait un diff
de stats faux quand les deux mains étaient occupées.
"""

from dataclasses import dataclass

import pytest

from app.application.use_cases.equip_item import EquipPlan, plan_equip
from app.shared.enums import EquipmentSlot, ItemSlotType


@dataclass
class FakeItem:
    equipment_slot: str | None
    requires_two_hands: bool = False
    id: int = 1


ARME_1 = EquipmentSlot.ARME_1.value
ARME_2 = EquipmentSlot.ARME_2.value
ACC = [EquipmentSlot.ACCESSOIRE_1.value, EquipmentSlot.ACCESSOIRE_2.value,
       EquipmentSlot.ACCESSOIRE_3.value]


def test_item_sans_emplacement_renvoie_none():
    assert plan_equip(FakeItem(None), {}) is None
    assert plan_equip(FakeItem(""), {}) is None


def test_tete_et_corps_ont_un_seul_emplacement():
    assert plan_equip(FakeItem("tete"), {}).target_slot == "tete"
    assert plan_equip(FakeItem("corps"), {}).target_slot == "corps"
    # occupé → on remplace au même endroit
    worn = {"tete": FakeItem("tete")}
    assert plan_equip(FakeItem("tete"), worn).target_slot == "tete"


def test_accessoires_remplissent_les_trous_dans_l_ordre():
    worn = {}
    for expected in ACC:
        plan = plan_equip(FakeItem("accessoire"), worn)
        assert plan.target_slot == expected
        worn[plan.target_slot] = FakeItem("accessoire")
    # les 3 pleins → remplace le premier
    assert plan_equip(FakeItem("accessoire"), worn).target_slot == ACC[0]


def test_deux_armes_a_une_main_occupent_les_deux_mains():
    worn = {}
    p1 = plan_equip(FakeItem(ItemSlotType.ARME.value), worn)
    assert p1.target_slot == ARME_1
    worn[ARME_1] = FakeItem(ItemSlotType.ARME.value)
    p2 = plan_equip(FakeItem(ItemSlotType.ARME.value), worn)
    assert p2.target_slot == ARME_2


def test_deux_mains_vise_toujours_arme_1():
    """Même si arme_2 est libre : une 2-mains ne se pose jamais en arme_2."""
    worn = {ARME_1: FakeItem(ItemSlotType.ARME.value)}
    plan = plan_equip(FakeItem(ItemSlotType.ARME.value, requires_two_hands=True), worn)
    assert plan.target_slot == ARME_1


@pytest.mark.parametrize(
    "worn_slots, attendu",
    [
        ([], ()),                      # mains vides : rien à libérer
        ([ARME_1], (ARME_1,)),
        ([ARME_2], (ARME_2,)),
        ([ARME_1, ARME_2], (ARME_1, ARME_2)),   # LE cas que le preview ratait
    ],
)
def test_deux_mains_libere_les_mains_occupees(worn_slots, attendu):
    worn = {s: FakeItem(ItemSlotType.ARME.value) for s in worn_slots}
    plan = plan_equip(FakeItem(ItemSlotType.ARME.value, requires_two_hands=True), worn)
    assert plan.freed_slots == attendu


def test_une_main_reprend_la_place_d_une_deux_mains():
    worn = {ARME_1: FakeItem(ItemSlotType.ARME.value, requires_two_hands=True)}
    plan = plan_equip(FakeItem(ItemSlotType.ARME.value), worn)
    assert plan == EquipPlan(ARME_1)
