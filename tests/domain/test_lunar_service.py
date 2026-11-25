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
    assert ls.DEFAULT_RULES["pleine_lune"] == LunarRule(strength=3, rewards=3)
    assert ls.DEFAULT_RULES["lune_de_sang"] == LunarRule(strength=6, rewards=5, spawn_rate=2)
    assert ls.effects_text(ls.DEFAULT_RULES["pleine_lune"]) == "puissance des monstres ×3 · XP, or et butin ×3"
    assert ls.validate({"pleine_lune": LunarRule(strength=0.5)})
    assert ls.validate(dict(ls.DEFAULT_RULES)) == []


def test_valeurs_de_l_auteur_et_tenebre_favorise_a_la_nouvelle_lune():
    assert ls.KINDS["nouvelle_lune"].name == "Nouvelle lune"
    assert ls.KINDS["eclipse_lunaire"].name == "Éclipse lunaire"
    assert ls.KINDS["eclipse_solaire"].name == "Éclipse solaire"
    assert ls.DEFAULT_RULES["eclipse_lunaire"] == LunarRule(strength=10, rewards=6, essences=5, spawn_rate=2)
    assert ls.DEFAULT_RULES["eclipse_solaire"] == LunarRule(strength=15, rewards=10, essences=10, spawn_rate=3)
    new = ls.DEFAULT_RULES["nouvelle_lune"]
    assert (new.strength, new.rewards, new.essences) == (1, 1, 3)
    assert ls.element_boost(new) == {"tenebre": 2}


def test_l_element_favorise_double_ses_apparitions(monkeypatch):
    import random

    from app.infrastructure.encounters import element_spot_resolver as r

    monkeypatch.setattr(r.farm_zone_loader, "get_spots", lambda ch: [
        {"element": "tenebre", "time": "always"}, {"element": "feu", "time": "always"}])
    monkeypatch.setattr(r.farm_zone_loader, "get_spot", lambda ch, el: {"element": el})
    monkeypatch.setattr(r.mob_element_weight_loader, "get_weights", lambda code: {})
    rng = random.Random(3)
    picks = [r.resolve_spawn(1, "m", rng=rng, element_boost={"tenebre": 2.0})[0] for _ in range(3000)]
    assert 0.62 < picks.count("tenebre") / len(picks) < 0.71      # 2/3 au lieu de 1/2


def test_la_puissance_annoncee_est_celle_du_score_affiche():
    """Retour des testeurs (25/11/2026) : « puissance ×3 » = le score affiché
    sur le monstre ×3, pour tous les monstres, seuls ou en meute."""
    import json
    from pathlib import Path

    from app.domain.services.power_score_service import PowerScoreService
    from app.domain.value_objects.stats import Stats

    pss = PowerScoreService()
    mobs = json.loads(Path("app/infrastructure/content/mobs.json").read_text(encoding="utf-8"))
    mobs = mobs if isinstance(mobs, list) else mobs.get("mobs", mobs)

    def score(m, f, d=1.0):
        return pss.calculate_from_stats(Stats(
            max_hp=max(1, round(m["max_hp"] * f)), attack=max(1, round(m["attack"] * f)),
            defense=round(m["defense"] * d), crit_chance=m.get("crit_chance", 0),
            crit_damage=m.get("crit_damage", 100), dodge=m.get("dodge", 0), speed=m.get("speed", 1)))

    for m in mobs:
        for power in (3, 6, 10, 15):
            for pack in (1.0, 0.87, 0.73):
                guess = ls.stat_factor(m["max_hp"] * pack, m["defense"], power)
                f = ls.fit_power(lambda x: score(m, pack * x), power, guess)
                # Au plus 2 % d'écart : l'ATK monte par points entiers (ATK 8 du slime…).
                gap = abs(score(m, pack * f) - power * score(m, pack))
                assert gap <= max(power, 0.02 * power * score(m, pack)), (m["code"], power, pack, gap)
        # Défense lunaire relevée : elle compte dans la puissance annoncée.
        f = ls.stat_factor(m["max_hp"], m["defense"], 3, defense_factor=2)
        assert abs(score(m, f, 2) / score(m, 1) / 3 - 1) < 0.03 or f == 1.0
    assert ls.stat_factor(100, 5, 1) == 1.0
