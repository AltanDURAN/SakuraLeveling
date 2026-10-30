"""Événements lunaires des zones (30/10/2026) : pleine lune, lune de sang
(une sur trois), nuit noire, éclipses — sur le ciel réel de Paris."""

from datetime import UTC, datetime, timedelta

from app.domain.services import astronomy, lunar_service as ls
from app.domain.services.lunar_service import LunarRule


def test_une_pleine_lune_sur_trois_est_une_lune_de_sang():
    fulls = [e for e in ls.upcoming(datetime(2026, 10, 30, tzinfo=UTC), days=400)
             if e.code in ("pleine_lune", "lune_de_sang")]
    blood = [e.code == "lune_de_sang" for e in fulls]
    assert len(fulls) >= 12 and sum(blood) == len(fulls) // 3 or sum(blood) == len(fulls) // 3 + 1
    first = blood.index(True)
    assert all(b == ((i - first) % 3 == 0) for i, b in enumerate(blood))


def test_la_pleine_lune_dure_du_coucher_au_lever_du_soleil():
    event = ls.active_event(datetime(2026, 11, 24, 20, tzinfo=UTC))
    assert event is not None and event.code in ("pleine_lune", "lune_de_sang")
    rise, sets = astronomy.sun_times(datetime(2026, 11, 24, 11, tzinfo=UTC))
    assert abs(event.start - sets) < timedelta(minutes=1)
    assert ls.active_event(datetime(2026, 11, 24, 12, tzinfo=UTC)) is None     # de jour : rien


def test_l_eclipse_l_emporte_sur_la_pleine_lune():
    at = datetime(2026, 8, 28, 4, 10, tzinfo=UTC)                  # éclipse partielle visible
    assert ls.active_event(at).code == "eclipse_lunaire"
    assert ls.active_event(at - timedelta(hours=4)).code in ("pleine_lune", "lune_de_sang")
    off = {"eclipse_lunaire": LunarRule(enabled=False)}
    assert ls.active_event(at, off).code in ("pleine_lune", "lune_de_sang")


def test_effets_par_defaut():
    assert ls.DEFAULT_RULES["pleine_lune"] == LunarRule(strength=2, rewards=3)
    assert ls.DEFAULT_RULES["lune_de_sang"] == LunarRule(strength=3, rewards=5, spawn_rate=2)
    assert ls.effects_text(ls.DEFAULT_RULES["pleine_lune"]) == "monstres ×2 plus forts · XP, or et butin ×3"
    assert ls.validate({"pleine_lune": LunarRule(strength=0.5)})
    assert ls.validate(dict(ls.DEFAULT_RULES)) == []
