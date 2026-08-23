"""Le mana doit pouvoir venir de TOUTES les sources de stats.

Le moteur lisait déjà `mana_max` / `mana_regeneration` sur l'équipement, la
classe et l'arbre, mais l'admin ne permettait pas d'en saisir — et les
PANOPLIES ne le géraient pas du tout. Ces tests verrouillent les quatre
sources d'un coup.
"""

from app.domain.services.set_bonus_service import SetBonuses
from app.domain.services.stats_service import StatsService
from app.domain.value_objects.skill_bonuses import SkillBonuses
from app.shared.enums import STAT_EMOJIS, STAT_LABELS
from tests.domain.test_stats_service import (
    build_class_definition,
    build_equipment_item,
    build_player_profile,
)

BASE_MANA, BASE_REGEN = 100, 5


def _stats(**kwargs):
    return StatsService().calculate_player_stats(
        profile=build_player_profile(level=1), **kwargs
    )


def test_equipement_peut_donner_du_mana():
    item = build_equipment_item("baton", "Bâton", {"mana_max": 40,
                                                   "mana_regeneration": 3})
    s = _stats(equipped_items=[item], active_class=None)
    assert s.mana_max == BASE_MANA + 40
    assert s.mana_regeneration == BASE_REGEN + 3


def test_classe_peut_donner_du_mana():
    cls = build_class_definition({"mana_max": 30, "mana_regeneration": 2})
    s = _stats(equipped_items=[], active_class=cls)
    assert s.mana_max == BASE_MANA + 30
    assert s.mana_regeneration == BASE_REGEN + 2


def test_arbre_peut_donner_du_mana():
    s = _stats(equipped_items=[], active_class=None,
               skill_bonuses=SkillBonuses(mana_max_flat=25,
                                          mana_regeneration_flat=4))
    assert s.mana_max == BASE_MANA + 25
    assert s.mana_regeneration == BASE_REGEN + 4


def test_panoplie_peut_donner_du_mana():
    """Nouveau : les panoplies ne géraient AUCUN mana avant."""
    s = _stats(equipped_items=[], active_class=None,
               set_bonuses=SetBonuses(mana_max_flat=50, mana_regeneration_flat=5))
    assert s.mana_max == BASE_MANA + 50
    assert s.mana_regeneration == BASE_REGEN + 5


def test_sources_de_mana_se_cumulent():
    item = build_equipment_item("baton", "Bâton", {"mana_max": 40})
    s = _stats(
        equipped_items=[item],
        active_class=build_class_definition({"mana_max": 30}),
        skill_bonuses=SkillBonuses(mana_max_flat=25),
        set_bonuses=SetBonuses(mana_max_flat=50),
    )
    assert s.mana_max == BASE_MANA + 40 + 30 + 25 + 50


def test_panoplie_ne_dilue_pas_le_mana_des_autres_sources():
    """Invariant : toute reconstruction de Stats doit REPORTER le mana.
    Une panoplie sans bonus de mana ne doit pas effacer celui de l'arbre."""
    s = _stats(equipped_items=[], active_class=None,
               skill_bonuses=SkillBonuses(mana_max_flat=25,
                                          mana_regeneration_flat=4),
               set_bonuses=SetBonuses(attack_flat=10))
    assert s.mana_max == BASE_MANA + 25
    assert s.mana_regeneration == BASE_REGEN + 4


def test_mana_expose_dans_les_libelles_admin():
    """L'UI admin se sert de ces tables : sans entrée, la stat est invisible."""
    for stat in ("mana_max", "mana_regeneration"):
        assert stat in STAT_LABELS
        assert stat in STAT_EMOJIS
