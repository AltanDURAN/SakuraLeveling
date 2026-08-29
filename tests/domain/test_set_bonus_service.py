"""Tests du SetBonusService — panoplies à 2 paliers (2 et 4 pièces).

Système simplifié : SEULS les emplacements de panoplie comptent — tête, corps
et les deux mains. Les accessoires en sont volontairement exclus, d'où un
maximum de 4 pièces.
"""

from datetime import UTC, datetime

from app.domain.entities.item_definition import ItemDefinition
from app.domain.entities.player_equipment_item import PlayerEquipmentItem
from app.domain.services.set_bonus_service import SetBonusService
from app.shared.enums import EquipmentSlot

_NOW = datetime.now(UTC)

_SAMPLE_DEFS = {
    "iron": {
        "name": "Acier",
        "icon": "🛡️",
        "tiers": [
            {"min_pieces": 2, "type": "defense_flat", "value": 3},
            {"min_pieces": 4, "type": "defense_flat", "value": 8},
        ],
    },
    "gobelin": {
        "name": "Gobeline",
        "icon": "👹",
        "tiers": [
            {"min_pieces": 2, "type": "crit_chance_flat", "value": 1},
            {"min_pieces": 4, "type": "crit_chance_flat", "value": 4},
        ],
    },
}

_TETE = EquipmentSlot.TETE.value
_CORPS = EquipmentSlot.CORPS.value
_ARME_1 = EquipmentSlot.ARME_1.value
_ARME_2 = EquipmentSlot.ARME_2.value
_ACC_1 = EquipmentSlot.ACCESSOIRE_1.value


def _eq(slot, code, family, requires_two_hands=False, item_id=1):
    item = ItemDefinition(
        id=item_id, code=code, name=code, description="",
        category="tete", rarity="common",
        stackable=False, max_stack=None,
        sell_price=1, buy_price=1, icon=None,
        stat_bonuses=None, equipment_slot=slot,
        requires_two_hands=requires_two_hands, family=family,
        created_at=_NOW, updated_at=_NOW,
    )
    return PlayerEquipmentItem(
        id=item_id, player_id=1, slot=slot, item_definition=item,
        created_at=_NOW, updated_at=_NOW,
    )


def test_aucun_bonus_sous_le_premier_palier():
    bonuses = SetBonusService(_SAMPLE_DEFS).aggregate(
        [_eq(_TETE, "iron_helm", "iron")]
    )
    assert bonuses.defense_flat == 0


def test_palier_2_actif_a_deux_pieces():
    bonuses = SetBonusService(_SAMPLE_DEFS).aggregate([
        _eq(_TETE, "iron_helm", "iron", item_id=1),
        _eq(_CORPS, "iron_armor", "iron", item_id=2),
    ])
    assert bonuses.defense_flat == 3


def test_palier_max_a_quatre_pieces():
    bonuses = SetBonusService(_SAMPLE_DEFS).aggregate([
        _eq(_TETE, "h", "iron", item_id=1),
        _eq(_CORPS, "c", "iron", item_id=2),
        _eq(_ARME_1, "a1", "iron", item_id=3),
        _eq(_ARME_2, "a2", "iron", item_id=4),
    ])
    assert bonuses.defense_flat == 8


def test_le_palier_haut_remplace_le_bas():
    """Les paliers ne se cumulent pas : seul le plus haut atteint compte."""
    bonuses = SetBonusService(_SAMPLE_DEFS).aggregate([
        _eq(_TETE, "h", "iron", item_id=1),
        _eq(_CORPS, "c", "iron", item_id=2),
        _eq(_ARME_1, "a1", "iron", item_id=3),
    ])
    assert bonuses.defense_flat == 3  # 3 pièces → palier 2, pas 2+8


def test_les_accessoires_ne_comptent_pas():
    """Décision produit : les accessoires sont hors panoplie."""
    bonuses = SetBonusService(_SAMPLE_DEFS).aggregate([
        _eq(_TETE, "h", "iron", item_id=1),
        _eq(_ACC_1, "bague", "iron", item_id=2),
    ])
    assert bonuses.defense_flat == 0  # 1 seule pièce comptée


def test_plusieurs_familles_cumulent_independamment():
    bonuses = SetBonusService(_SAMPLE_DEFS).aggregate([
        _eq(_TETE, "h", "iron", item_id=1),
        _eq(_CORPS, "c", "iron", item_id=2),
        _eq(_ARME_1, "a1", "gobelin", item_id=3),
        _eq(_ARME_2, "a2", "gobelin", item_id=4),
    ])
    assert bonuses.defense_flat == 3
    assert bonuses.crit_chance_flat == 1


def test_famille_inconnue_ignoree_silencieusement():
    bonuses = SetBonusService(_SAMPLE_DEFS).aggregate([
        _eq(_TETE, "x", "inconnue", item_id=1),
        _eq(_CORPS, "y", "inconnue", item_id=2),
    ])
    assert bonuses.defense_flat == 0


def test_item_sans_famille_ignore():
    bonuses = SetBonusService(_SAMPLE_DEFS).aggregate([
        _eq(_TETE, "h", "", item_id=1),
        _eq(_CORPS, "c", "", item_id=2),
    ])
    assert bonuses.defense_flat == 0


def test_arme_deux_mains_compte_pour_deux_pieces():
    """Une 2-mains occupe les deux emplacements : elle vaut 2 pièces."""
    bonuses = SetBonusService(_SAMPLE_DEFS).aggregate([
        _eq(_ARME_1, "espadon", "iron", requires_two_hands=True, item_id=1),
    ])
    assert bonuses.defense_flat == 3


def test_panoplie_complete_avec_une_deux_mains():
    """tête + corps + 2-mains = 4 pièces → palier maximal."""
    bonuses = SetBonusService(_SAMPLE_DEFS).aggregate([
        _eq(_TETE, "h", "iron", item_id=1),
        _eq(_CORPS, "c", "iron", item_id=2),
        _eq(_ARME_1, "espadon", "iron", requires_two_hands=True, item_id=3),
    ])
    assert bonuses.defense_flat == 8


def test_deux_fois_la_meme_arme_ne_compte_qu_une_fois():
    """Porter deux exemplaires de la MÊME arme ne vaut qu'une pièce : sinon on
    compléterait une panoplie en dupliquant un seul objet."""
    bonuses = SetBonusService(_SAMPLE_DEFS).aggregate([
        _eq(_TETE, "h", "iron", item_id=1),
        _eq(_CORPS, "c", "iron", item_id=2),
        _eq(_ARME_1, "dague", "iron", item_id=9),
        _eq(_ARME_2, "dague", "iron", item_id=9),   # même définition
    ])
    assert bonuses.defense_flat == 3   # 3 pièces → palier 2, PAS le palier 4


def test_deux_armes_differentes_completent_la_panoplie():
    """Les mêmes emplacements, mais deux armes DISTINCTES → 4 pièces."""
    bonuses = SetBonusService(_SAMPLE_DEFS).aggregate([
        _eq(_TETE, "h", "iron", item_id=1),
        _eq(_CORPS, "c", "iron", item_id=2),
        _eq(_ARME_1, "epee", "iron", item_id=8),
        _eq(_ARME_2, "dague", "iron", item_id=9),
    ])
    assert bonuses.defense_flat == 8
