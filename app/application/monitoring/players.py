"""Une ligne par joueur : tout ce qu'on compare d'un joueur à l'autre
(temps de jeu, rythme, or par heure, investissement) — la liste des joueurs,
sa fiche, le haut de la vue d'ensemble et les alertes la partagent."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from app.application.monitoring.dataset import Dataset, to_local
from app.domain.services.monitoring import kinds, progression as prog
from app.domain.services.monitoring.stats import percentile_rank

#: Fenêtre du rythme de progression (projections).
PACE_DAYS = 14

SPEC_ROLES = {"Assassin": "DPS", "Rempart": "Tank", "Soigneur": "Soutien"}


@dataclass
class PlayerRow:
    pid: int
    name: str
    is_admin: bool
    level: int
    gold: int
    power: int
    rank: str
    spec: str
    role: str
    created_at: datetime | None
    last_active: datetime | None
    play_min: float                 # sur la période
    play_min_7d: float
    active_days: int                # sur la période
    active_days_7d: int
    sessions: int
    avg_session_min: float
    combats: int
    wins: int
    deaths: int
    gold_created: int               # or créé (combats, quêtes…) sur la période
    gold_spent: int                 # or détruit (boutique, fusion…) sur la période
    xp_gained: int
    levels: int                     # niveaux gagnés sur la période (hors admin)
    unspent: int
    kills_per_day: float = 0.0      # rythme (kills équivalents / jour, 14 j)
    days_to_cap: int | None = None
    days_to_content_end: int | None = None
    investment: float = 0.0         # centile 0-100
    flags: list[str] = field(default_factory=list)

    @property
    def win_rate(self) -> float | None:
        return 100 * self.wins / self.combats if self.combats else None

    @property
    def gold_per_hour(self) -> float | None:
        return self.gold_created / (self.play_min / 60) if self.play_min >= 30 else None

    @property
    def days_since_active(self) -> float | None:
        if self.last_active is None:
            return None
        return (datetime.now(UTC).replace(tzinfo=None) - self.last_active).total_seconds() / 86400

    @property
    def investment_label(self) -> str:
        v = self.investment
        return "Très investi" if v >= 85 else "Investi" if v >= 60 else "Régulier" if v >= 35 else "Occasionnel"


def content_end_level(ds: Dataset) -> int:
    """Dernier niveau des zones ouvertes (fin du contenu actuel)."""
    ranks = {r for _, r in ds.zones.values() if r}
    ends = [prog.ZONE_LEVELS[r][1] for r in ranks if r in prog.ZONE_LEVELS]
    return max(ends, default=prog.LEVEL_CAP)


def _pace(ds: Dataset, pid: int) -> float:
    """XP par jour sur les PACE_DAYS derniers jours (photos), en kills équivalents."""
    info = ds.players[pid]
    now_total = prog.total_xp(info.level, info.xp)
    ref_day = ds.today - timedelta(days=PACE_DAYS)
    snap = ds.snapshot_on(pid, ref_day)
    if snap is not None:
        start_total, start_at = snap.xp_total, snap.taken_at
    else:
        rows = ds.snapshots_by_player.get(pid) or []
        if rows:
            start_total, start_at = rows[0].xp_total, rows[0].taken_at
        elif info.created_at is not None:
            start_total, start_at = 0, info.created_at
        else:
            return 0.0
    if start_at.tzinfo is not None:
        start_at = start_at.replace(tzinfo=None)
    days = max(1.0, (ds.now_naive - start_at).total_seconds() / 86400)
    return prog.kills_per_day((now_total - start_total) / days, info.level)


def build_rows(ds: Dataset) -> list[PlayerRow]:
    if "rows" in ds._cache:
        return ds._cache["rows"]
    end_level = content_end_level(ds)
    rows = []
    for pid, info in ds.players.items():
        evs = [e for e in ds.by_player.get(pid, ()) if ds.in_window(e)]
        combats = [e for e in evs if e.kind == kinds.COMBAT]
        gold = [e for e in evs if e.kind == kinds.GOLD]
        sessions = [s for s in ds.sessions(pid) if s.end >= ds.start]
        snap = ds.latest_snapshot(pid)
        spec = (snap.data.get("spec") if snap else "") or ""
        kpd = _pace(ds, pid)
        row = PlayerRow(
            pid=pid, name=info.name, is_admin=info.is_admin, level=info.level, gold=info.gold,
            power=snap.power if snap else 0, rank=(snap.rank if snap else "") or "",
            spec=spec, role=SPEC_ROLES.get(spec, "Généraliste"),
            created_at=info.created_at, last_active=ds.last_active(pid),
            play_min=ds.play_minutes(pid), play_min_7d=ds.play_minutes(pid, 7),
            active_days=len({d for d in ds.active_days(pid) if d > ds.today - timedelta(days=ds.days)}),
            active_days_7d=len({d for d in ds.active_days(pid) if d > ds.today - timedelta(days=7)}),
            sessions=len(sessions),
            avg_session_min=sum(s.minutes for s in sessions) / len(sessions) if sessions else 0.0,
            combats=len(combats),
            wins=sum(1 for e in combats if e.data.get("res") == "win"),
            deaths=sum(1 for e in combats if e.data.get("res") == "death"),
            gold_created=sum(e.gold for e in gold if kinds.flow_of(e.ref, e.gold) == kinds.CREATION),
            gold_spent=-sum(e.gold for e in gold if kinds.flow_of(e.ref, e.gold) == kinds.DESTRUCTION),
            xp_gained=sum(e.xp for e in combats) + sum(e.xp for e in evs if e.kind == kinds.QUEST),
            levels=sum(max(0, e.qty - int(e.data.get("from", e.qty))) for e in evs
                       if e.kind == kinds.LEVEL_UP and e.data.get("src") != "admin"),
            unspent=info.stat_points + info.skill_points,
            kills_per_day=kpd,
        )
        row.days_to_cap = prog.project_days(info.level, info.xp, kpd) if kpd > 0.5 else None
        row.days_to_content_end = (prog.project_days(info.level, info.xp, kpd, end_level)
                                   if kpd > 0.5 and info.level < end_level else (0 if info.level >= end_level else None))
        rows.append(row)
    # Investissement : moyenne des centiles (temps de jeu, jours joués,
    # combats, niveau) parmi les joueurs actifs de la période.
    pool = [r for r in rows if r.play_min > 0] or rows
    metrics = [lambda r: r.play_min, lambda r: r.active_days, lambda r: r.combats, lambda r: r.level]
    columns = [[m(r) for r in pool] for m in metrics]
    for r in rows:
        r.investment = 0.0 if r.play_min <= 0 and r.combats == 0 else (
            sum(percentile_rank(col, m(r)) for col, m in zip(columns, metrics)) / len(metrics))
    ds._cache["rows"] = rows
    return rows


def local_str(t: datetime | None) -> str:
    return to_local(t).strftime("%d/%m %Hh%M") if t else "—"
