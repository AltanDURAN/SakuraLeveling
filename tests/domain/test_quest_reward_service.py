"""Une quête pèse le même poids à tous les niveaux, sans écraser la courbe."""

from app.domain.services.progression_service import LEVEL_CAP, XP_PER_KILL_COEF
from app.domain.services.quest_reward_service import QUEST_REFERENCE_LEVEL, scale_reward


def test_au_niveau_de_reference_le_montant_ecrit_est_le_montant_recu():
    assert scale_reward(72, QUEST_REFERENCE_LEVEL) == 72


def test_la_recompense_vaut_le_meme_nombre_de_victoires_a_tout_niveau():
    ratios = {
        round(scale_reward(1000, level) / (XP_PER_KILL_COEF * level), 6)
        for level in (10, 20, 50, 100)
    }
    assert len(ratios) == 1


def test_le_raid_peut_garder_des_montants_de_niveau_1():
    assert scale_reward(50, 30, reference_level=1) == 1500


def test_niveau_borne():
    assert scale_reward(20, 0) == 1
    assert scale_reward(20, 500) == 20 * LEVEL_CAP // QUEST_REFERENCE_LEVEL
