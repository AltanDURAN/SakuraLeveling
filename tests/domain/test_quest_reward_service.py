"""Une quête pèse le même nombre de victoires à tous les niveaux."""

from app.domain.services.progression_service import LEVEL_CAP, XP_PER_KILL_COEF
from app.domain.services.quest_reward_service import scale_reward


def test_au_niveau_1_le_montant_ecrit_est_le_montant_recu():
    assert scale_reward(50, 1) == 50


def test_la_recompense_vaut_le_meme_nombre_de_victoires_a_tout_niveau():
    for level in (1, 10, 50, 99):
        kills = scale_reward(50, level) / (XP_PER_KILL_COEF * level)
        assert kills == 50 / XP_PER_KILL_COEF


def test_niveau_borne():
    assert scale_reward(10, 0) == 10
    assert scale_reward(10, 500) == 10 * LEVEL_CAP
