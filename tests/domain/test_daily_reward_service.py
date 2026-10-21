from datetime import datetime, timedelta, UTC

from app.domain.services.daily_reward_service import (
    daily_gold,
    missed_days,
    streak_after_absence,
    streak_bonus_pct,
)


def test_or_indexe_sur_le_niveau():
    assert daily_gold(1, 0) == 20
    assert daily_gold(50, 0) == 1000
    assert daily_gold(100, 0) == 2000


def test_bonus_de_serie_plafonne_a_30_jours():
    assert streak_bonus_pct(1) == 3
    assert streak_bonus_pct(30) == 90
    assert streak_bonus_pct(365) == 90
    assert daily_gold(50, 30) == daily_gold(50, 400) == 1900


def test_jours_manques():
    window = datetime(2026, 10, 21, 22, 0, tzinfo=UTC)
    assert missed_days(None, window) == 0
    assert missed_days(window, window - timedelta(hours=3)) == 0  # pas encore ouvert
    assert missed_days(window, window + timedelta(hours=23)) == 0  # réclamé dans la fenêtre
    assert missed_days(window, window + timedelta(hours=25)) == 1
    assert missed_days(window, window + timedelta(days=3, hours=1)) == 3
    assert missed_days(window.replace(tzinfo=None), window + timedelta(days=2)) == 2


def test_chaque_jour_manque_divise_la_serie_par_deux():
    assert streak_after_absence(40, 0) == 40
    assert streak_after_absence(40, 1) == 20
    assert streak_after_absence(40, 2) == 10
    assert streak_after_absence(3, 5) == 0
