"""Le ciel de Paris calculé (`astronomy`) comparé aux éphémérides publiées
(IMCCE / NASA) : phases, lever et coucher du Soleil, éclipses visibles."""

from datetime import UTC, datetime, timedelta

from app.domain.services import astronomy as a


def _k(when: datetime) -> int:
    return a.lunation(when)


def close(when: datetime, expected: datetime, minutes: float = 3) -> bool:
    return abs(when - expected) <= timedelta(minutes=minutes)


def test_pleines_et_nouvelles_lunes_a_la_minute():
    fm = {a.full_moon(k).date(): a.full_moon(k) for k in range(_k(datetime(2025, 9, 1, tzinfo=UTC)),
                                                              _k(datetime(2026, 12, 1, tzinfo=UTC)))}
    assert close(fm[datetime(2025, 9, 7).date()], datetime(2025, 9, 7, 18, 9, tzinfo=UTC))
    assert close(fm[datetime(2026, 3, 3).date()], datetime(2026, 3, 3, 11, 38, tzinfo=UTC))
    assert close(fm[datetime(2026, 10, 26).date()], datetime(2026, 10, 26, 4, 12, tzinfo=UTC))
    assert close(a.new_moon(_k(datetime(2025, 3, 29, 12, tzinfo=UTC))), datetime(2025, 3, 29, 10, 58, tzinfo=UTC))


def test_lever_et_coucher_du_soleil_a_paris():
    rise, sets = a.sun_times(datetime(2026, 10, 30, 11, tzinfo=UTC))
    assert close(rise, datetime(2026, 10, 30, 6, 34, tzinfo=UTC), 2)      # 7 h 34 à Paris
    assert close(sets, datetime(2026, 10, 30, 16, 33, tzinfo=UTC), 2)     # 17 h 33


def test_nuit_de_la_pleine_lune():
    start, end = a.night_around(datetime(2026, 10, 26, 4, 12, tzinfo=UTC))   # pleine lune de nuit
    assert start.date() == datetime(2026, 10, 25).date() and end.date() == datetime(2026, 10, 26).date()
    start, end = a.night_around(datetime(2026, 11, 24, 14, 53, tzinfo=UTC))  # de jour : la nuit la plus proche
    assert start.date() == datetime(2026, 11, 24).date() and start.hour == 16


def test_eclipses_visibles_de_paris():
    found = {}
    for k in range(_k(datetime(2021, 1, 1, tzinfo=UTC)), _k(datetime(2029, 2, 1, tzinfo=UTC))):
        for eclipse in (a.solar_eclipse(k), a.lunar_eclipse(k)):
            if eclipse is not None:
                found[(eclipse.kind, eclipse.peak.date().isoformat())] = eclipse
    assert set(found) == {
        ("soleil", "2021-06-10"), ("lune", "2022-05-16"), ("soleil", "2022-10-25"),
        ("lune", "2023-10-28"), ("lune", "2024-09-18"), ("lune", "2025-03-14"),
        ("soleil", "2025-03-29"), ("lune", "2025-09-07"), ("soleil", "2026-08-12"),
        ("lune", "2026-08-28"), ("soleil", "2027-08-02"), ("lune", "2028-01-12"),
        ("soleil", "2028-01-26"), ("lune", "2028-12-31"),
    }
    # Le 12/08/2026, ~92 % du Soleil caché à Paris (totale en Espagne) ;
    # le 07/09/2025, Lune levée en pleine totalité.
    assert 0.88 < found[("soleil", "2026-08-12")].magnitude < 0.96
    assert found[("lune", "2025-09-07")].total
    # Le 03/03/2026, éclipse totale… mais Lune couchée à Paris.
    assert a.lunar_eclipse(_k(datetime(2026, 3, 3, tzinfo=UTC))) is None
