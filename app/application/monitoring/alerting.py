"""Alertes : faits du jeu → règles (`domain.services.monitoring.alerts`) →
historique en base (`monitoring_alerts` : depuis quand, sourdine, envoi aux
admins). Le bot les recalcule toutes les heures ; la page Alertes aussi, à
chaque ouverture."""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.application.monitoring import analysis
from app.application.monitoring.dataset import Dataset, to_local, utc_naive
from app.application.monitoring.players import build_rows, content_end_level
from app.domain.services.monitoring import activity, alerts as rules, kinds
from app.domain.services.monitoring.stats import median, robust_z
from app.infrastructure.db.models.monitoring_model import MonitoringAlertModel
from app.infrastructure.monitoring.monitoring_loader import MonitoringSettings, get_settings

STAT_LABELS = analysis.STAT_LABELS


def _now() -> datetime:
    """Maintenant, en UTC naïf (comme toutes les heures de la base)."""
    return datetime.now(UTC).replace(tzinfo=None)


def player_facts(ds: Dataset) -> list[rules.PlayerFacts]:
    rows = build_rows(ds)
    now = ds.now_naive
    week = now - timedelta(days=7)
    out = []
    # Puissance : comparée aux joueurs de ±3 niveaux (photo la plus récente).
    powers = [(r.level, r.power) for r in rows if r.power > 0 and not r.is_admin]
    senders: dict[int, set[int]] = defaultdict(set)
    received: Counter = Counter()
    for e in ds.of_kind(kinds.TRANSFER, days=14):
        to = e.data.get("to")
        if to is not None and e.player_id is not None:
            senders[int(to)].add(e.player_id)
            received[int(to)] += e.gold
    gold_events: dict[int, list] = defaultdict(list)
    for e in ds.of_kind(kinds.GOLD, days=ds.days + 1):
        gold_events[e.player_id].append(e)
    end_level = content_end_level(ds)
    for r in rows:
        info = ds.players[r.pid]
        times = [t for t in ds.activity_times(r.pid) if t >= week]
        sessions = [s for s in ds.sessions(r.pid) if s.end >= week]
        level_ups = [e for e in ds.by_player.get(r.pid, ())
                     if e.kind == kinds.LEVEL_UP and e.at >= now - timedelta(days=1) and e.data.get("src") != "admin"]
        peers = [p for lv, p in powers if abs(lv - r.level) <= 3]
        unexplained = unexplained_gold(ds, r.pid, gold_events.get(r.pid, []))
        stuck = 0
        recent = [x for x in ds.snapshots_by_player.get(r.pid, ()) if x.day >= ds.today - timedelta(days=14)]
        same = [x for x in recent if x.level == r.level]
        if len(same) >= 3 and r.level < end_level:
            played = [d for d in ds.active_days(r.pid) if any(x.day == d for x in same)]
            stuck = len(same) if len(played) >= 3 else 0
        out.append(rules.PlayerFacts(
            player_id=r.pid, name=r.name, level=r.level, power=r.power, gold=r.gold, is_admin=r.is_admin,
            play_hours_7d=r.play_min_7d / 60,
            creation_gold_7d=sum(e.gold for e in ds.by_player.get(r.pid, ())
                                 if e.kind == kinds.GOLD and e.at >= week and kinds.flow_of(e.ref, e.gold) == kinds.CREATION),
            levels_24h=sum(max(0, e.qty - int(e.data.get("from", e.qty))) for e in level_ups),
            longest_session_h=max((x.minutes for x in sessions), default=0) / 60,
            max_active_hours_day=max(activity.active_hours_per_day(to_local(t) for t in times).values(), default=0),
            regularity=activity.regularity([e.at for e in ds.by_player.get(r.pid, ())
                                            if e.kind == kinds.INTERACTION and e.at >= week]),
            max_burst=activity.max_burst([e.at for e in ds.by_player.get(r.pid, ())
                                          if e.kind == kinds.INTERACTION and e.at >= week]),
            gold_senders=len(senders.get(r.pid, ())), gold_received=received.get(r.pid, 0),
            unexplained_gold=unexplained,
            days_since_active=r.days_since_active,
            investment_pct=r.investment, unspent_points=r.unspent, stuck_days=stuck,
            power_z=robust_z(r.power, peers) if r.power and len(peers) >= 5 else 0.0,
        ))
    return out


def unexplained_gold(ds: Dataset, pid: int, gold_events: list, days: int = 7) -> int:
    """Or apparu (ou disparu) hors du journal sur les `days` derniers jours :
    chaque photo est comparée à la précédente (solde + mouvements entre leurs
    deux numéros d'événement), puis la dernière au solde réel."""
    lo = ds.today - timedelta(days=days)
    chain = [s for s in ds.snapshots_by_player.get(pid, ()) if "eid" in s.data and s.day >= lo]
    if not chain:
        return 0
    events = sorted(gold_events, key=lambda e: e.id)

    def moved(after: int, upto: int) -> int:
        return sum(e.gold for e in events if after < e.id <= upto)

    total = 0
    for a, b in zip(chain, chain[1:]):
        total += b.gold - (a.gold + moved(int(a.data["eid"]), int(b.data["eid"])))
    last = chain[-1]
    total += ds.players[pid].gold - (last.gold + moved(int(last.data["eid"]), ds.last_event_id))
    return total


def mob_facts(ds: Dataset) -> list[rules.MobFacts]:
    return [rules.MobFacts(code=m["code"], name=m["name"], fights=m["fights"], wins=m["kills"],
                           deaths=round(m["death_pct"] * max(1, round(m["fights"] * m["group"])) / 100),
                           participants=max(1, round(m["fights"] * m["group"])), avg_win_turns=m["turns"])
            for m in analysis.mob_table(ds)]


def server_facts(ds: Dataset) -> rules.ServerFacts:
    now_local = to_local(ds.now)
    rows = build_rows(ds)
    facts = rules.ServerFacts(now=ds.now)
    # Activité d'aujourd'hui contre les 7 jours précédents, À LA MÊME HEURE.
    def active_until(day_offset: int) -> int:
        end = now_local - timedelta(days=day_offset)
        lo = utc_naive(end.replace(hour=0, minute=0, second=0, microsecond=0))
        hi = utc_naive(end)
        return sum(1 for pid in ds.players if any(lo <= t < hi for t in ds.activity_times(pid)))
    facts.dau_today = active_until(0)
    base = [active_until(k) for k in range(1, 8)]
    facts.dau_baseline = statistics.mean(base) if base else 0
    supply = analysis.money_supply(ds, days=8)
    if len(supply) == 8 and supply[0] > 0 and supply[-1] > 0:
        facts.money_growth_pct = 100 * ((supply[-1] / supply[0]) ** (1 / 7) - 1)
    golds = sorted((p.gold for p in ds.players.values()), reverse=True)
    if golds and sum(golds):
        top = golds[:max(1, len(golds) // 10)]
        facts.top10_share_pct = 100 * sum(top) / sum(golds)
        facts.holders = len(golds)
    first_day = {pid: to_local(p.created_at).date() for pid, p in ds.players.items() if p.created_at}
    cohorts = activity.retention(first_day, {pid: ds.active_days(pid) for pid in ds.players}, ds.today)
    recent = [c for c in cohorts[-4:] if c.retained.get(7) is not None]
    if recent:
        size = sum(c.size for c in recent)
        facts.retention_d7_pct = sum(c.retained[7] * c.size for c in recent) / size if size else None
        facts.retention_d7_base = size
    meta = _meta_tops(ds)
    facts.gear_top, facts.spec_top, facts.stat_top = meta
    caps = [r.days_to_cap for r in rows if r.days_to_cap is not None and r.active_days_7d >= 3 and not r.is_admin]
    design = analysis.design_days()
    if caps and design:
        facts.pace_ratio_pct = 100 * median(caps) / design
        facts.pace_players = len(caps)
    end = content_end_level(ds)
    facts.content_end_reached = sum(1 for r in rows if r.level >= end and not r.is_admin)
    facts.content_end_level = end
    ahead = sorted((r for r in rows if r.days_to_content_end and r.level < end and not r.is_admin),
                   key=lambda r: r.days_to_content_end)
    if ahead:
        facts.content_end_days, facts.content_end_level = ahead[0].days_to_content_end, end
        facts.content_end_player = ahead[0].name
    facts.admin_gold_7d = sum(e.gold for e in ds.of_kind(kinds.GOLD, days=7) if e.ref == "admin" and e.gold > 0)
    errors = ds.of_kind(kinds.ERROR, days=1)
    facts.errors_24h = len(errors)
    facts.error_commands = tuple(c for c, _ in Counter(e.ref or "?" for e in errors).most_common())
    sales = defaultdict(list)
    for e in ds.of_kind(kinds.MARKET_SALE):
        sales[e.ref].append(e)
    for ref, evs in sales.items():
        if len(evs) < 3:
            continue
        unit = [e.gold / max(1, e.qty) for e in evs]
        med = median(unit)
        ratio = get_settings().thresholds["market_price_ratio"]
        for e, u in zip(evs, unit):
            if med > 0 and (u >= ratio * med or u <= med / ratio):
                facts.market.append((e.player_id, ds.name(e.player_id), ds.item_name(ref), e.gold, round(med * max(1, e.qty))))
    return facts


def _meta_tops(ds: Dataset):
    snaps = [s for pid in ds.players if (s := ds.latest_snapshot(pid)) is not None and not ds.players[pid].is_admin]
    equipped = [s for s in snaps if s.data.get("gear")]
    worn = Counter(code for s in equipped for code in {g[0] for g in s.data["gear"]})
    gear_top = None
    if worn:
        code, n = worn.most_common(1)[0]
        gear_top = (code, ds.item_name(code), 100 * n / len(equipped), len(equipped))
    specs = Counter(s.data.get("spec") for s in snaps if s.data.get("spec"))
    spec_top = None
    if specs:
        name, n = specs.most_common(1)[0]
        spec_top = (name, 100 * n / sum(specs.values()), sum(specs.values()))
    dominant = Counter()
    counted = 0
    for s in snaps:
        pts = s.data.get("pts") or [0, 0, 0]
        if sum(pts) >= 5:
            counted += 1
            top = max(range(3), key=lambda i: pts[i])
            if pts[top] / sum(pts) > 0.8:
                dominant[STAT_LABELS[top]] += 1
    stat_top = None
    if dominant:
        name, n = dominant.most_common(1)[0]
        stat_top = (name, 100 * n / counted, counted)
    return gear_top, spec_top, stat_top


def compute(ds: Dataset, settings: MonitoringSettings | None = None) -> list[rules.Alert]:
    settings = settings or get_settings()
    return rules.evaluate(player_facts(ds), mob_facts(ds), server_facts(ds), settings.thresholds, settings.rules)


@dataclass
class AlertView:
    alert: rules.Alert
    first_seen: datetime | None
    muted_until: datetime | None
    notified: bool

    @property
    def first_seen_local(self) -> datetime | None:
        return to_local(self.first_seen) if self.first_seen else None

    @property
    def muted(self) -> bool:
        return self.muted_until is not None and self.muted_until > _now()


def sync(session: Session, current: list[rules.Alert], now: datetime | None = None) -> list[rules.Alert]:
    """Met l'historique à jour ; renvoie les alertes APPARUES maintenant."""
    now = utc_naive(now) if now is not None else _now()
    rows = {r.key: r for r in session.execute(select(MonitoringAlertModel)).scalars()}
    fresh = []
    seen = set()
    for a in current:
        seen.add(a.key)
        row = rows.get(a.key)
        if row is None:
            session.add(MonitoringAlertModel(key=a.key, code=a.code, severity=a.severity, title=a.title[:200],
                                             message=a.message, player_id=a.player_id, first_seen=now, last_seen=now))
            fresh.append(a)
            continue
        if row.resolved_at is not None:        # revenue : elle repart de zéro
            row.first_seen, row.resolved_at, row.notified_at = now, None, None
            fresh.append(a)
        row.severity, row.title, row.message, row.last_seen = a.severity, a.title[:200], a.message, now
    for key, row in rows.items():
        if key not in seen and row.resolved_at is None:
            row.resolved_at = now
    session.commit()
    return fresh


def views(session: Session, current: list[rules.Alert]) -> list[AlertView]:
    rows = {r.key: r for r in session.execute(select(MonitoringAlertModel)).scalars()}
    out = []
    for a in current:
        row = rows.get(a.key)
        out.append(AlertView(a, row.first_seen if row else None, row.muted_until if row else None,
                             bool(row and row.notified_at)))
    return out


def history(session: Session, limit: int = 40) -> list[MonitoringAlertModel]:
    """Alertes résolues récemment (ce qui s'est passé sans qu'on le voie)."""
    return list(session.execute(select(MonitoringAlertModel).where(MonitoringAlertModel.resolved_at.is_not(None))
                                .order_by(MonitoringAlertModel.resolved_at.desc()).limit(limit)).scalars())


def mute(session: Session, key: str, days: float) -> bool:
    row = session.get(MonitoringAlertModel, key)
    if row is None:
        return False
    row.muted_until = None if days <= 0 else _now() + timedelta(days=days)
    session.commit()
    return True


def to_notify(session: Session, settings: MonitoringSettings | None = None) -> list[MonitoringAlertModel]:
    """Alertes ouvertes, non envoyées, non en sourdine, assez graves."""
    settings = settings or get_settings()
    now = _now()
    rows = session.execute(select(MonitoringAlertModel).where(MonitoringAlertModel.resolved_at.is_(None),
                                                              MonitoringAlertModel.notified_at.is_(None))).scalars()
    return [r for r in rows if settings.notifies(r.severity) and not (r.muted_until and r.muted_until > now)]
