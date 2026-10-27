"""Règles pures de la tour solo (`tower_service`)."""

from app.domain.services import tower_service as ts


def test_l_etage_n_est_du_niveau_n_et_un_boss_tous_les_10():
    assert [ts.floor_level(f) for f in (1, 37, 100)] == [1, 37, 100]
    assert [f for f in range(1, 101) if ts.is_boss_floor(f)] == list(range(10, 101, 10))
    assert ts.next_floor(0) == 1 and ts.next_floor(99) == 100 and ts.next_floor(100) is None


def test_premier_passage_en_victoires_de_son_niveau():
    normal = ts.first_clear_reward(37, "corne")
    assert (normal.gold, normal.xp, normal.materials) == (8 * 3 * 37, round(4 * 6.25 * 37), ())
    boss = ts.first_clear_reward(40, "corne")
    assert boss.gold == 3 * 8 * 3 * 40 and boss.materials == (("corne", 13),)


def test_recompense_du_jour_selon_le_record_pas_le_niveau():
    assert ts.daily_reward(0, "corne").is_empty
    reward = ts.daily_reward(57, "sang")
    assert reward.gold == 570 and reward.materials == (("sang", 6),) and reward.xp == 0
