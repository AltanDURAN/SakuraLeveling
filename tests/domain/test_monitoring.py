"""Surveillance : règles pures (sessions, heures pleines et creuses,
rétention, projections, alertes)."""

from datetime import date, datetime, timedelta

from app.domain.services.monitoring import activity, alerts, kinds, progression as prog
from app.domain.services.monitoring.stats import gini, percentile, percentile_rank, robust_z

T0 = datetime(2026, 11, 2, 20, 0)


def test_sessions_coupees_par_une_pause_de_plus_de_15_minutes():
    times = [T0, T0 + timedelta(minutes=5), T0 + timedelta(minutes=14),
             T0 + timedelta(minutes=40), T0 + timedelta(minutes=41)]
    s = activity.build_sessions(times)
    assert len(s) == 2
    assert s[0].events == 3 and s[0].minutes == 14 + activity.SESSION_TAIL_MINUTES
    assert s[1].events == 2


def test_temps_de_jeu_coupe_a_minuit():
    s = activity.build_sessions([datetime(2026, 11, 2, 23, 50), datetime(2026, 11, 3, 0, 5),
                                 datetime(2026, 11, 3, 0, 10)])
    assert len(s) == 1
    per_day = activity.minutes_by_day(s, lambda t: t)
    assert round(per_day[date(2026, 11, 2)]) == 10 and round(per_day[date(2026, 11, 3)]) == 12


def test_heures_pleines_et_creuses_y_compris_a_cheval_sur_minuit():
    profile = [50] * 24
    for h in (21, 22):
        profile[h] = 100
    for h in (23, 0, 1, 2):
        profile[h] = 1
    busy, quiet = activity.busy_and_quiet(profile)
    assert busy[0].start == 21 and busy[0].end == 23
    assert quiet[0].start == 23 and quiet[0].end == 3 and quiet[0].label == "23h – 3h"


def test_un_script_est_regulier_un_humain_non():
    script = [T0 + timedelta(seconds=45 * i) for i in range(100)]
    import random
    rng = random.Random(1)
    human, t = [], T0
    for _ in range(100):
        t += timedelta(seconds=rng.uniform(5, 400))
        human.append(t)
    assert activity.regularity(script) < 0.05
    assert activity.regularity(human) > 0.4
    assert activity.regularity(script[:10]) is None      # trop peu pour juger


def test_rafale_d_actions():
    times = [T0 + timedelta(seconds=i) for i in range(40)] + [T0 + timedelta(hours=1)]
    assert activity.max_burst(times) == 40


def test_retention_par_semaine_d_arrivee():
    monday = date(2026, 10, 5)
    first = {1: monday, 2: monday, 3: monday + timedelta(days=1)}
    active = {1: {monday, monday + timedelta(days=8)}, 2: {monday}, 3: {monday + timedelta(days=2)}}
    rows = activity.retention(first, active, today=monday + timedelta(days=60))
    assert len(rows) == 1 and rows[0].size == 3
    assert round(rows[0].retained[7]) == 33          # seul le joueur 1 est revenu la semaine suivante
    assert round(rows[0].retained[1]) == 33          # le joueur 3, le lendemain
    young = activity.retention(first, active, today=monday + timedelta(days=3))
    assert young[0].retained[7] is None              # cohorte trop jeune


def test_petites_statistiques():
    assert percentile([1, 2, 3, 4], 50) == 2.5
    assert percentile_rank([1, 2, 3, 4], 4) == 87.5
    assert gini([10, 10, 10]) == 0 and gini([0, 0, 100]) > 0.6
    assert robust_z(100, [10, 11, 12, 10, 11, 100]) > 3


def test_xp_cumulee_et_projection():
    assert prog.total_xp(1, 0) == 0
    assert prog.total_xp(2, 0) == prog.xp_to_reach(2) > 0
    fast = prog.project_days(10, 0, kills_daily=60)
    slow = prog.project_days(10, 0, kills_daily=20)
    assert fast < slow
    assert prog.project_days(100, 0, 10) == 0
    assert prog.project_days(5, 0, 0) is None


def test_courbe_de_reference_du_design():
    hour = prog.reference_curve(60, 800)
    half = prog.reference_curve(30, 800)
    assert hour[0] >= 1 and hour == sorted(hour)
    d100 = prog.day_reaching(hour, 100)
    assert d100 is not None and d100 < prog.day_reaching(half, 100)
    assert prog.zone_for_level(25) == "E" and prog.zone_for_level(100) == "S"


def test_sources_d_or():
    assert kinds.flow_of("combat", 50) == kinds.CREATION
    assert kinds.flow_of("boutique", -50) == kinds.DESTRUCTION
    assert kinds.flow_of("evenement", -20) == kinds.DESTRUCTION
    assert kinds.flow_of("virement", 100) == kinds.TRANSFER_FLOW
    assert kinds.flow_of(None, 5) == kinds.OTHER


# ------------------------------------------------------------------ alertes
def _p(pid, **kw):
    return alerts.PlayerFacts(player_id=pid, name=f"J{pid}", **kw)


def _codes(found):
    return {a.code for a in found}


def test_chaque_regle_de_comportement_se_declenche():
    server = alerts.ServerFacts(now=T0)
    normal = [_p(i, play_hours_7d=5, creation_gold_7d=5000, level=20, power=1000) for i in range(1, 6)]
    suspects = [
        _p(10, unexplained_gold=50_000),
        _p(11, play_hours_7d=5, creation_gold_7d=40_000),
        _p(12, regularity=0.03),
        _p(13, max_active_hours_day=23),
        _p(14, longest_session_h=9),
        _p(15, max_burst=60),
        _p(16, levels_24h=15),
        _p(17, power_z=5),
        _p(18, gold_senders=4, gold_received=9000),
        _p(19, investment_pct=90, days_since_active=5),
        _p(20, unspent_points=20),
        _p(21, stuck_days=7),
    ]
    found = alerts.evaluate(normal + suspects, [], server)
    assert {"unexplained_gold", "gold_rate", "bot_like", "marathon", "spam", "level_speed", "power_outlier",
            "gold_hub", "churn_risk", "unspent_points", "stuck"} <= _codes(found)
    assert all(a.player_id not in range(1, 6) for a in found if a.player_id)
    assert found[0].severity == alerts.CRITICAL            # le plus grave d'abord


def test_les_comptes_admin_ne_declenchent_rien_et_une_regle_se_coupe():
    server = alerts.ServerFacts(now=T0)
    admin = _p(1, is_admin=True, unexplained_gold=10**6, max_burst=500)
    assert alerts.evaluate([admin], [], server) == []
    cheat = _p(2, unexplained_gold=10**6)
    assert alerts.evaluate([cheat], [], server, enabled={"unexplained_gold": False}) == []
    assert alerts.evaluate([cheat], [], server, thresholds={"unexplained_gold_min": 2 * 10**6}) == []


def test_regles_d_equilibrage_et_de_serveur():
    mobs = [alerts.MobFacts("slime", "Slime", fights=100, wins=100, participants=100, avg_win_turns=3),
            alerts.MobFacts("liche", "Liche", fights=40, wins=10, deaths=20, participants=60, avg_win_turns=40),
            alerts.MobFacts("rare", "Rare", fights=3, wins=0, participants=3)]
    server = alerts.ServerFacts(
        now=T0, dau_today=2, dau_baseline=10, money_growth_pct=15, top10_share_pct=80, holders=20,
        retention_d7_pct=10, retention_d7_base=12, gear_top=("perle", "Perle", 90, 10),
        spec_top=("Assassin", 85, 10), stat_top=("Attaque", 90, 10), pace_ratio_pct=40, pace_players=5,
        content_end_reached=2, content_end_level=80, admin_gold_7d=100_000, errors_24h=9,
        error_commands=("tour",), market=[(3, "J3", "Perle", 25_000, 400)])
    found = _codes(alerts.evaluate([], mobs, server))
    assert {"mob_too_easy", "mob_too_hard", "meta_gear", "meta_spec", "meta_stats", "pace", "content_end",
            "inflation", "hoarding", "admin_gold", "dau_drop", "retention", "errors", "market_price"} <= found
    hard = [a for a in alerts.evaluate([], mobs, server) if a.code == "mob_too_hard"]
    assert [a.ref for a in hard] == ["liche"]               # 3 combats : on ne juge pas


def test_chaque_seuil_appartient_a_une_regle():
    codes = {r.code for r in alerts.RULES}
    assert all(t.rule in codes for t in alerts.THRESHOLDS)
    assert len({t.key for t in alerts.THRESHOLDS}) == len(alerts.THRESHOLDS)
