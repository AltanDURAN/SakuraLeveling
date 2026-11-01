"""Rapport hebdomadaire : une semaine (lundi → dimanche, heure de Paris)
comparée à la précédente, et les faits marquants rédigés en clair."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.application.monitoring import dataset as dsm
from app.application.monitoring.dataset import Dataset, utc_naive
from app.domain.services.gear_service import RARITY_LABELS
from app.domain.services.monitoring import activity, kinds
from app.domain.services.monitoring.alerts import SEVERITY_ORDER
from app.domain.services.pacing_service import PARIS
from app.infrastructure.db.models.monitoring_model import MonitoringAlertModel
from app.shared.formatters import format_int


def _week_bounds(ds: Dataset, weeks_ago: int):
    monday = ds.today - timedelta(days=ds.today.weekday() + 7 * weeks_ago)
    start = datetime.combine(monday, time.min, PARIS)
    return monday, utc_naive(start), utc_naive(start + timedelta(days=7))


def _metrics(ds: Dataset, lo: datetime, hi: datetime) -> dict:
    evs = [e for e in ds.events if lo <= e.at < hi]
    act = [e for e in evs if e.kind in kinds.ACTIVITY_KINDS and e.player_id is not None]
    players = {e.player_id for e in act}
    minutes = 0.0
    for pid in players:
        minutes += sum(s.minutes for s in activity.build_sessions(e.at for e in act if e.player_id == pid))
    combats = [e for e in evs if e.kind == kinds.COMBAT]
    encounters = {e.data.get("enc") for e in combats}
    won = {e.data.get("enc") for e in combats if e.data.get("res") in ("win", "death")}
    gold = [e for e in evs if e.kind == kinds.GOLD]
    created = sum(e.gold for e in gold if kinds.flow_of(e.ref, e.gold) == kinds.CREATION)
    destroyed = -sum(e.gold for e in gold if kinds.flow_of(e.ref, e.gold) == kinds.DESTRUCTION)
    new = [p for p in ds.players.values() if p.created_at and lo <= p.created_at < hi]
    per_player = Counter()
    for e in act:
        per_player[e.player_id] += 1
    mobs = Counter()
    for e in combats:
        if e.data.get("res") == "win":
            mobs[e.ref] += 1
    big_drops = [e for e in evs if e.kind == kinds.GEAR_DROP and e.data.get("rarity") in ("epic", "legendary", "mythic")]
    return {
        "players": len(players), "new": len(new), "hours": minutes / 60,
        "combats": len(encounters), "win_pct": 100 * len(won) / len(encounters) if encounters else None,
        "created": created, "destroyed": destroyed,
        "levels": sum(1 for e in evs if e.kind == kinds.LEVEL_UP and e.data.get("src") != "admin"),
        "rank_ups": [(ds.name(e.player_id), e.ref, e.qty) for e in evs if e.kind == kinds.RANK_UP],
        "drops": Counter(e.data.get("rarity") for e in big_drops),
        "mythics": [(ds.name(e.player_id), ds.item_name(e.ref)) for e in big_drops if e.data.get("rarity") == "mythic"],
        "top": [(ds.name(pid), n) for pid, n in per_player.most_common(5)],
        "mobs": [(ds.mob_name(code), n) for code, n in mobs.most_common(5)],
        "purchases": sum(1 for e in evs if e.kind == kinds.SHOP_BUY),
        "fusions": sum(1 for e in evs if e.kind == kinds.FUSION),
        "new_names": [p.name for p in new][:12],
    }


def _change(a, b) -> float | None:
    if a is None or b in (None, 0):
        return None
    return 100 * (a - b) / b


def weekly(session: Session, weeks_ago: int = 0) -> dict:
    ds = dsm.cached(session, days=7 * (weeks_ago + 2) + 1, include_admins=False, history_days=7 * (weeks_ago + 2) + 1)
    monday, lo, hi = _week_bounds(ds, weeks_ago)
    _, plo, phi = _week_bounds(ds, weeks_ago + 1)
    cur, prev = _metrics(ds, lo, hi), _metrics(ds, plo, phi)
    alerts = list(session.execute(select(MonitoringAlertModel).where(
        MonitoringAlertModel.first_seen >= lo, MonitoringAlertModel.first_seen < hi)).scalars())
    alerts.sort(key=lambda a: (SEVERITY_ORDER.index(a.severity) if a.severity in SEVERITY_ORDER else 9, a.title))
    highlights = []
    ch = _change(cur["players"], prev["players"])
    if ch is not None:
        highlights.append(("📈" if ch >= 0 else "📉",
                           f"{cur['players']} joueurs actifs ({'+' if ch >= 0 else ''}{ch:.0f} % par rapport à la semaine d'avant)."))
    if cur["new"]:
        highlights.append(("🌸", f"{cur['new']} nouveaux joueurs : " + ", ".join(cur["new_names"]) + "."))
    if cur["rank_ups"]:
        highlights.append(("🏅", f"{len(cur['rank_ups'])} promotions de rang, dont "
                           + ", ".join(f"{n} (rang {r})" for n, r, _ in cur["rank_ups"][:4]) + "."))
    if cur["mythics"]:
        highlights.append(("🔴", "Pièce mythique trouvée : " + ", ".join(f"{n} ({i})" for n, i in cur["mythics"]) + "."))
    if cur["created"]:
        ratio = 100 * cur["destroyed"] / cur["created"]
        highlights.append(("💰", f"{format_int(cur['created'])} or créé, {format_int(cur['destroyed'])} détruit "
                           f"({ratio:.0f} %) : la masse d'or {'grossit' if ratio < 100 else 'diminue'}."))
    if cur["top"]:
        highlights.append(("🔥", f"Le plus actif : {cur['top'][0][0]}."))
    if alerts:
        crit = sum(1 for a in alerts if a.severity in SEVERITY_ORDER[:2])
        highlights.append(("🚨", f"{len(alerts)} alertes apparues, dont {crit} critiques ou sérieuses."))
    return {
        "monday": monday, "sunday": monday + timedelta(days=6), "cur": cur, "prev": prev,
        "changes": {k: _change(cur[k], prev[k]) for k in ("players", "new", "hours", "combats", "created",
                                                          "destroyed", "levels", "purchases", "fusions")},
        "alerts": alerts, "highlights": highlights,
        "drops": [(RARITY_LABELS.get(r, r), cur["drops"].get(r, 0)) for r in ("epic", "legendary", "mythic")],
        "in_progress": weeks_ago == 0,
    }
