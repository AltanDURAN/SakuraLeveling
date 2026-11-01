"""Activité : sessions de jeu, heures pleines et creuses, rétention.

Le temps de jeu se déduit des traces : chaque interaction (commande, bouton)
et chaque combat. Deux traces à moins de `SESSION_GAP_MINUTES` d'écart sont
la même session ; on ajoute `SESSION_TAIL_MINUTES` à la fin (le joueur
regarde encore le combat ou lit la réponse).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta

SESSION_GAP_MINUTES = 15
SESSION_TAIL_MINUTES = 2


@dataclass(frozen=True)
class PlaySession:
    start: datetime
    end: datetime
    events: int

    @property
    def minutes(self) -> float:
        return (self.end - self.start).total_seconds() / 60


def build_sessions(times: Iterable[datetime], gap_minutes: float = SESSION_GAP_MINUTES,
                   tail_minutes: float = SESSION_TAIL_MINUTES) -> list[PlaySession]:
    ordered = sorted(times)
    if not ordered:
        return []
    gap = timedelta(minutes=gap_minutes)
    tail = timedelta(minutes=tail_minutes)
    out: list[PlaySession] = []
    start = last = ordered[0]
    count = 1
    for t in ordered[1:]:
        if t - last > gap:
            out.append(PlaySession(start, last + tail, count))
            start, count = t, 0
        last = t
        count += 1
    out.append(PlaySession(start, last + tail, count))
    return out


def minutes_by_day(sessions: Sequence[PlaySession], to_local) -> dict[date, float]:
    """Temps de jeu par jour LOCAL (une session à cheval sur minuit est coupée)."""
    out: dict[date, float] = defaultdict(float)
    for s in sessions:
        start, end = to_local(s.start), to_local(s.end)
        while start.date() < end.date():
            midnight = datetime.combine(start.date() + timedelta(days=1), datetime.min.time(), start.tzinfo)
            out[start.date()] += (midnight - start).total_seconds() / 60
            start = midnight
        out[start.date()] += (end - start).total_seconds() / 60
    return dict(out)


def heatmap(local_times: Iterable[datetime]) -> list[list[int]]:
    """Compte par [jour de la semaine (lundi = 0)][heure]."""
    grid = [[0] * 24 for _ in range(7)]
    for t in local_times:
        grid[t.weekday()][t.hour] += 1
    return grid


def hour_profile(grid: Sequence[Sequence[int]]) -> list[int]:
    return [sum(row[h] for row in grid) for h in range(24)]


@dataclass(frozen=True)
class HourRange:
    start: int          # heure incluse
    end: int            # heure EXCLUE (24 = minuit)
    level: float        # moyenne relative au pic (0-1)

    @property
    def label(self) -> str:
        return f"{self.start}h – {self.end % 24}h"


def busy_and_quiet(profile: Sequence[float], busy_ratio: float = 0.7,
                   quiet_ratio: float = 0.2) -> tuple[list[HourRange], list[HourRange]]:
    """Plages d'heures pleines (≥ busy_ratio × pic) et creuses (≤ quiet_ratio ×
    pic). Une plage peut passer minuit (22h – 2h)."""
    peak = max(profile) if profile else 0
    if peak <= 0:
        return [], []

    def ranges(test) -> list[HourRange]:
        hours = [h for h in range(24) if test(profile[h] / peak)]
        if not hours:
            return []
        if len(hours) == 24:
            return [HourRange(0, 24, sum(profile) / 24 / peak)]
        groups: list[list[int]] = []
        for h in hours:
            if groups and h == groups[-1][-1] + 1:
                groups[-1].append(h)
            else:
                groups.append([h])
        if len(groups) > 1 and groups[0][0] == 0 and groups[-1][-1] == 23:
            groups[0] = groups.pop() + groups[0]          # à cheval sur minuit
        return [HourRange(g[0], g[-1] + 1, sum(profile[h] for h in g) / len(g) / peak) for g in groups]

    busy = sorted(ranges(lambda r: r >= busy_ratio), key=lambda r: -r.level)
    quiet = sorted(ranges(lambda r: r <= quiet_ratio), key=lambda r: r.level)
    return busy, quiet


def regularity(times: Sequence[datetime], max_gap_seconds: float = 600) -> float | None:
    """Coefficient de variation des écarts entre deux actions rapprochées. Un
    humain est irrégulier (≥ 0,5) ; un script tape à intervalles fixes (≈ 0).
    None sous 40 écarts : pas de verdict sur trop peu."""
    ordered = sorted(times)
    gaps = [(b - a).total_seconds() for a, b in zip(ordered, ordered[1:])]
    gaps = [g for g in gaps if 0 < g <= max_gap_seconds]
    if len(gaps) < 40:
        return None
    m = sum(gaps) / len(gaps)
    var = sum((g - m) ** 2 for g in gaps) / len(gaps)
    return (var ** 0.5) / m if m else None


def max_burst(times: Sequence[datetime], window_seconds: float = 60) -> int:
    """Plus grand nombre d'actions dans une fenêtre glissante."""
    ordered = sorted(times)
    best, lo = 0, 0
    for hi, t in enumerate(ordered):
        while (t - ordered[lo]).total_seconds() > window_seconds:
            lo += 1
        best = max(best, hi - lo + 1)
    return best


def active_hours_per_day(local_times: Iterable[datetime]) -> dict[date, int]:
    """Nombre d'heures distinctes avec une action, par jour local."""
    seen: dict[date, set[int]] = defaultdict(set)
    for t in local_times:
        seen[t.date()].add(t.hour)
    return {d: len(h) for d, h in seen.items()}


@dataclass(frozen=True)
class CohortRow:
    start: date                 # lundi de la semaine d'arrivée
    size: int
    #: Part (0-100) de la cohorte encore active N jours après l'arrivée ;
    #: None si la cohorte n'a pas encore cet âge.
    retained: dict[int, float | None]


def retention(first_day: dict[int, date], active_days: dict[int, set[date]], today: date,
              offsets: Sequence[int] = (1, 7, 14, 30)) -> list[CohortRow]:
    """Rétention par semaine d'arrivée : un joueur compte « retenu à J+N »
    s'il a joué au moins un jour de J+N à J+N+6 (J+1 : le lendemain ou le
    surlendemain) — mesurer un seul jour pile pénaliserait un joueur du
    week-end."""
    cohorts: dict[date, list[int]] = defaultdict(list)
    for pid, d in first_day.items():
        cohorts[d - timedelta(days=d.weekday())].append(pid)
    rows = []
    for start in sorted(cohorts):
        members = cohorts[start]
        retained: dict[int, float | None] = {}
        for n in offsets:
            window = 2 if n == 1 else 7
            eligible = [p for p in members if first_day[p] + timedelta(days=n + window - 1) <= today]
            if not eligible:
                retained[n] = None
                continue
            kept = sum(1 for p in eligible if any(
                first_day[p] + timedelta(days=n) <= d < first_day[p] + timedelta(days=n + window)
                for d in active_days.get(p, ())))
            retained[n] = 100 * kept / len(eligible)
        rows.append(CohortRow(start, len(members), retained))
    return rows


def rolling_active(active_days: dict[int, set[date]], days: Sequence[date], window: int) -> list[int]:
    """Joueurs actifs sur les `window` derniers jours, pour chaque jour."""
    out = []
    for d in days:
        lo = d - timedelta(days=window - 1)
        out.append(sum(1 for ds in active_days.values() if any(lo <= x <= d for x in ds)))
    return out
