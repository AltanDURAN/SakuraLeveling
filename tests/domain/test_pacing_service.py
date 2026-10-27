"""Rythme du jeu (27/10/2026) : délais d'apparition, heures calmes, meutes,
rendez-vous du raid — réglables depuis l'admin."""

import random
from datetime import date, datetime, timedelta

from app.domain.services import pacing_service as ps
from app.domain.services.pacing_service import PARIS, Pacing, RaidPacing, ZoneOverride, ZonePacing
from app.infrastructure.pacing.pacing_loader import parse


def at(hour: int, minute: int = 0, day: int = 28) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=PARIS)


def test_les_valeurs_par_defaut_sont_celles_d_avant():
    assert ps.DEFAULT == parse({})
    z, r = ps.DEFAULT.zones, ps.DEFAULT.raid
    assert (z.respawn_min_minutes, z.respawn_max_minutes, z.join_window_minutes, z.pack_chance_pct) == (1, 1, 5, 10)
    assert (ps.fight_label(r), ps.close_label(r)) == ("21h", "20h50")
    assert ps.validate(ps.DEFAULT) == []


def test_le_delai_est_tire_dans_la_plage_de_la_zone():
    zones = ZonePacing(respawn_min_minutes=2, respawn_max_minutes=8, flee_respawn_minutes=15)
    now = at(12)
    rng = random.Random(1)
    delays = [(ps.next_spawn_at(zones, None, now, rng=rng) - now).total_seconds() / 60 for _ in range(200)]
    assert 2 <= min(delays) < 3 and 7 < max(delays) <= 8
    assert ps.next_spawn_at(zones, None, now, fled=True) == now + timedelta(minutes=15)
    own = ZoneOverride(respawn_min_minutes=30)                      # sans max : délai fixe
    assert ps.next_spawn_at(zones, own, now, rng=rng) == now + timedelta(minutes=30)


def test_heures_calmes_y_compris_a_cheval_sur_minuit():
    night = ZonePacing(quiet_start_hour=1, quiet_end_hour=8)
    assert ps.in_quiet_hours(night, at(3)) and not ps.in_quiet_hours(night, at(8))
    wrap = ZonePacing(quiet_start_hour=23, quiet_end_hour=7)
    assert ps.in_quiet_hours(wrap, at(23, 30)) and ps.in_quiet_hours(wrap, at(2))
    assert not ps.in_quiet_hours(wrap, at(12))
    assert not ps.in_quiet_hours(ZonePacing(), at(3))               # début = fin : désactivé


def test_repartition_des_meutes():
    assert ps.pack_size_weights(ZonePacing(pack_of_three_pct=25)) == {2: 75, 3: 25}


def test_inscriptions_et_assaut_du_raid():
    raid = RaidPacing(fight_hour=20, fight_minute=30, registration_close_minutes=15)
    assert (ps.fight_label(raid), ps.close_label(raid)) == ("20h30", "20h15")
    assert not ps.registration_closed(raid, at(20, 14)) and ps.registration_closed(raid, at(23, 59))
    assert not ps.registration_closed(raid, at(0, 1, day=29))       # rouvre à minuit
    assert ps.fight_due(raid, at(20, 31), None)
    assert not ps.fight_due(raid, at(20, 31), date(2026, 10, 28))   # déjà lancé aujourd'hui
    assert not ps.fight_due(raid, at(20, 29), None)
    assert not ps.fight_due(raid, at(21, 0), None)                  # rattrapage : 15 min
    assert ps.next_fight_at(raid, at(21)) == at(20, 30, day=29)


def test_validation():
    bad = Pacing(zones=ZonePacing(respawn_min_minutes=5, respawn_max_minutes=2, join_window_minutes=60),
                 overrides={1: ZoneOverride(respawn_min_minutes=0.1)},
                 raid=RaidPacing(fight_hour=0, fight_minute=5, registration_close_minutes=10))
    errors = " ".join(ps.validate(bad))
    for part in ("maximum ne peut pas", "rejoindre", "Zone 1", "même jour"):
        assert part in errors


def test_lecture_du_json():
    pacing = parse({"zones": {"respawn_min_minutes": 3, "respawn_max_minutes": "6"},
                    "zone_overrides": {"42": {"paused": True}}, "raid": {"fight_hour": 20}})
    assert pacing.zones.respawn_max_minutes == 6.0 and pacing.zones.join_window_minutes == 5
    assert pacing.override(42).paused and not pacing.override(7).paused
    assert pacing.raid.fight_hour == 20 and pacing.raid.fight_minute == 0
