"""Le mana doit pouvoir venir de TOUTES les sources de stats.

En saison 1 le mana est une stat SECONDAIRE : elle se cumule à PLAT (jamais en
pourcentage du socle), et les points de stats ne la touchent pas. Ces tests
verrouillent les trois sources restantes — équipement, arbre, panoplie — et
l'invariant du projet : aucune reconstruction de `Stats` ne doit perdre le mana.
"""

from app.domain.services.set_bonus_service import SetBonuses
from app.domain.services.stats_service import (
    BASE_MANA_MAX,
    BASE_MANA_REGENERATION,
    StatsService,
)
from app.domain.value_objects.skill_bonuses import SkillBonuses
from app.shared.enums import STAT_EMOJIS, STAT_LABELS
from tests.domain.test_stats_service import build_item, build_profile


def _stats(**kwargs):
    return StatsService().calculate_player_stats(
        profile=build_profile(), **kwargs,
    )


def test_sans_aucune_source_le_mana_vaut_sa_base():
    s = _stats(equipped_items=[])
    assert s.mana_max == BASE_MANA_MAX
    assert s.mana_regeneration == BASE_MANA_REGENERATION


def test_le_mana_vient_de_l_equipement():
    s = _stats(equipped_items=[build_item({"mana_max": 50, "mana_regeneration": 3})])
    assert s.mana_max == BASE_MANA_MAX + 50
    assert s.mana_regeneration == BASE_MANA_REGENERATION + 3


def test_le_mana_vient_de_l_arbre():
    s = _stats(
        equipped_items=[],
        skill_bonuses=SkillBonuses(mana_max_flat=40, mana_regeneration_flat=2),
    )
    assert s.mana_max == BASE_MANA_MAX + 40
    assert s.mana_regeneration == BASE_MANA_REGENERATION + 2


def test_le_mana_vient_des_panoplies():
    s = _stats(
        equipped_items=[],
        set_bonuses=SetBonuses(mana_max_flat=25, mana_regeneration_flat=1),
    )
    assert s.mana_max == BASE_MANA_MAX + 25
    assert s.mana_regeneration == BASE_MANA_REGENERATION + 1


def test_les_sources_de_mana_se_cumulent():
    s = _stats(
        equipped_items=[build_item({"mana_max": 10})],
        skill_bonuses=SkillBonuses(mana_max_flat=20),
        set_bonuses=SetBonuses(mana_max_flat=30),
    )
    assert s.mana_max == BASE_MANA_MAX + 60


def test_le_mana_ne_descend_jamais_sous_zero():
    s = _stats(equipped_items=[build_item({"mana_max": -9999})])
    assert s.mana_max == 0


def test_le_mana_est_nommable_dans_l_interface():
    """L'admin doit pouvoir saisir ces stats : elles ont besoin d'un libellé
    et d'un emoji, sinon elles s'affichent en code brut."""
    for key in ("mana_max", "mana_regeneration"):
        assert key in STAT_LABELS and key in STAT_EMOJIS
