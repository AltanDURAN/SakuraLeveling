"""Panoplies saison 1 : paliers 2 / 4 / 7 par rareté, comptage cumulatif."""

from types import SimpleNamespace

import pytest

from app.domain.services.set_bonus_service import SetBonusService, panoplie_type, tier_for


def piece(rarity: str, two_hands: bool = False):
    return SimpleNamespace(
        rarity=rarity,
        item_definition=SimpleNamespace(requires_two_hands=two_hands),
    )


def total(pieces, kind="attack") -> float:
    return SetBonusService().aggregate(pieces, kind).total


def test_paliers():
    assert tier_for(1) == (0.0, 2)
    assert tier_for(2) == (1.0, 4)
    assert tier_for(5) == (1.5, 7)
    assert tier_for(7) == (3.0, None)


def test_rien_sous_deux_pieces():
    assert total([piece("legendary")]) == 0


@pytest.mark.parametrize("rarity, expected", [
    ("common", 6), ("rare", 12), ("epic", 18), ("legendary", 24), ("mythic", 33),
])
def test_set_d_une_seule_rarete(rarity, expected):
    # Bonus simple 2 % × multiplicateur de rareté × palier ×3.
    assert total([piece(rarity)] * 7) == expected


def test_exemple_de_l_auteur():
    # 5 rares + 1 épique + 1 légendaire = 7 commun, 7 peu commun, 7 rare,
    # 2 épique (et 1 légendaire, sans palier) : 6 + 3 + 3 + 2.
    pieces = [piece("rare")] * 5 + [piece("epic"), piece("legendary")]
    assert total(pieces) == 14


def test_ameliorer_une_piece_ne_fait_jamais_baisser_le_bonus():
    order = ["common", "uncommon", "rare", "epic", "legendary", "mythic"]
    pieces = ["rare"] * 7
    before = total([piece(r) for r in pieces])
    for i in range(7):
        for _ in range(3):
            nxt = order[min(order.index(pieces[i]) + 1, 5)]
            pieces[i] = nxt
            after = total([piece(r) for r in pieces])
            assert after >= before
            before = after


def test_deux_mains_compte_pour_deux():
    # 1 deux-mains + 5 pièces = 7 places.
    pieces = [piece("epic", two_hands=True)] + [piece("epic")] * 5
    assert total(pieces) == 18


def test_type_plat_et_fraction_pour_les_pourcentages():
    b = SetBonusService().aggregate([piece("epic")] * 4, "crit_damage")
    assert b.crit_damage_flat == round(4 * 3 * 1.5) and b.attack_percent == 0
    b = SetBonusService().aggregate([piece("epic")] * 4, "defense")
    assert b.total == 9 and b.defense_percent == pytest.approx(0.09)


def test_type_inconnu_retombe_sur_l_attaque():
    assert panoplie_type("vitesse").code == "attack"
