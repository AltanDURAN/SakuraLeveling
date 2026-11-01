"""Jeu de données de la surveillance : joueurs, journal et photos d'une
période, chargés UNE fois par page puis analysés en mémoire (quelques
dizaines de milliers de lignes : bien plus simple et assez rapide pour la
taille du serveur).

Les heures sont stockées en UTC ; tout ce qui se lit « au jour » ou « à
l'heure » (jour actif, carte de chaleur) est converti à l'heure de Paris.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from functools import cached_property

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.services.monitoring import activity, kinds
from app.domain.services.pacing_service import PARIS
from app.infrastructure.config.settings import settings
from app.infrastructure.db.models.item_model import ItemDefinitionModel
from app.infrastructure.db.models.mob_model import MobDefinitionModel
from app.infrastructure.db.models.monitoring_model import GameEventModel, PlayerDailySnapshotModel
from app.infrastructure.db.models.player_model import PlayerModel
from app.infrastructure.db.models.progression_model import PlayerProgressionModel
from app.infrastructure.db.models.resource_model import PlayerResourceModel


def to_local(t: datetime) -> datetime:
    if t.tzinfo is None:
        t = t.replace(tzinfo=UTC)
    return t.astimezone(PARIS)


def utc_naive(t: datetime) -> datetime:
    return t.astimezone(UTC).replace(tzinfo=None) if t.tzinfo else t


@dataclass(frozen=True)
class Event:
    id: int
    at: datetime            # UTC naïf
    kind: str
    player_id: int | None
    zone: str | None
    ref: str | None
    gold: int
    xp: int
    qty: int
    data: dict

    @property
    def local(self) -> datetime:
        return to_local(self.at)


@dataclass(frozen=True)
class Snapshot:
    day: date
    player_id: int
    taken_at: datetime
    level: int
    xp_total: int
    gold: int
    power: int
    rank: str
    kills: int
    combats: int
    wins: int
    gold_earned: int
    data: dict


@dataclass
class PlayerInfo:
    id: int
    discord_id: int
    name: str
    created_at: datetime | None
    last_seen_at: datetime | None
    is_admin: bool
    level: int = 1
    xp: int = 0
    gold: int = 0
    stat_points: int = 0
    skill_points: int = 0
    points: tuple[int, int, int] = (0, 0, 0)


@dataclass
class Dataset:
    now: datetime                       # UTC aware
    days: int
    include_admins: bool
    players: dict[int, PlayerInfo]
    events: list[Event]                 # période + 1 jour de marge avant
    snapshots: list[Snapshot]
    zones: dict[str, tuple[str, str]]   # salon → (nom, rang)
    mobs: dict[str, dict]
    items: dict[str, str]               # code → nom
    items_by_id: dict[int, tuple[str, str]]
    #: Monstres repartis sans combattant, comptés en base par (salon, heure
    #: UTC) : des dizaines de milliers de lignes qu'il est inutile de charger.
    flees: dict[tuple[str, datetime], int] = field(default_factory=dict)
    last_event_id: int = 0
    _cache: dict = field(default_factory=dict, repr=False)

    # ------------------------------------------------------------ bornes
    @property
    def start(self) -> datetime:
        """Début de la période (UTC naïf)."""
        return utc_naive(self.now) - timedelta(days=self.days)

    @property
    def now_naive(self) -> datetime:
        return utc_naive(self.now)

    @property
    def today(self) -> date:
        return to_local(self.now).date()

    def day_list(self, days: int | None = None) -> list[date]:
        n = days or self.days
        return [self.today - timedelta(days=n - 1 - i) for i in range(n)]

    def in_window(self, e: Event, days: float | None = None) -> bool:
        lo = self.now_naive - timedelta(days=days if days is not None else self.days)
        return e.at >= lo

    # ---------------------------------------------------------- filtres
    def of_kind(self, *kinds_: str, days: float | None = None) -> list[Event]:
        key = ("kind", kinds_, days)
        if key not in self._cache:
            self._cache[key] = [e for e in self.events if e.kind in kinds_ and self.in_window(e, days)]
        return self._cache[key]

    @cached_property
    def by_player(self) -> dict[int, list[Event]]:
        out: dict[int, list[Event]] = defaultdict(list)
        for e in self.events:
            if e.player_id is not None:
                out[e.player_id].append(e)
        return out

    def activity_times(self, pid: int) -> list[datetime]:
        key = ("times", pid)
        if key not in self._cache:
            self._cache[key] = sorted(e.at for e in self.by_player.get(pid, ()) if e.kind in kinds.ACTIVITY_KINDS)
        return self._cache[key]

    def sessions(self, pid: int) -> list[activity.PlaySession]:
        key = ("sessions", pid)
        if key not in self._cache:
            self._cache[key] = activity.build_sessions(self.activity_times(pid))
        return self._cache[key]

    def play_minutes(self, pid: int, days: float | None = None) -> float:
        lo = self.now_naive - timedelta(days=days if days is not None else self.days)
        return sum(s.minutes for s in self.sessions(pid) if s.end >= lo)

    def active_days(self, pid: int) -> set[date]:
        key = ("days", pid)
        if key not in self._cache:
            self._cache[key] = {to_local(t).date() for t in self.activity_times(pid)}
        return self._cache[key]

    def last_active(self, pid: int) -> datetime | None:
        times = self.activity_times(pid)
        last = times[-1] if times else None
        seen = self.players[pid].last_seen_at if pid in self.players else None
        if seen is not None and seen.tzinfo is not None:
            seen = utc_naive(seen)
        return max((t for t in (last, seen) if t is not None), default=None)

    @cached_property
    def active_players(self) -> list[int]:
        """Joueurs ayant joué pendant la période."""
        return self.active_in(self.days)

    def active_in(self, days: float, until: datetime | None = None) -> list[int]:
        """Joueurs ayant joué dans les `days` jours avant `until` (maintenant)."""
        hi = until or self.now_naive
        lo = hi - timedelta(days=days)
        return [pid for pid in self.players if any(lo <= t < hi for t in self.activity_times(pid))]

    # ---------------------------------------------------------- photos
    @cached_property
    def snapshots_by_player(self) -> dict[int, list[Snapshot]]:
        out: dict[int, list[Snapshot]] = defaultdict(list)
        for s in sorted(self.snapshots, key=lambda s: s.day):
            out[s.player_id].append(s)
        return out

    def latest_snapshot(self, pid: int) -> Snapshot | None:
        rows = self.snapshots_by_player.get(pid)
        return rows[-1] if rows else None

    def snapshot_on(self, pid: int, day: date) -> Snapshot | None:
        """Dernière photo au plus tard ce jour-là."""
        best = None
        for s in self.snapshots_by_player.get(pid, ()):
            if s.day <= day:
                best = s
        return best

    # ---------------------------------------------------------- libellés
    def zone_name(self, channel: str | None) -> str:
        return self.zones.get(channel or "", (f"Salon {channel}" if channel else "Hors zone", ""))[0]

    def zone_rank(self, channel: str | None) -> str:
        return self.zones.get(channel or "", ("", ""))[1]

    def mob_name(self, code: str | None) -> str:
        return (self.mobs.get(code or "") or {}).get("name", code or "?")

    def item_name(self, code: str | None) -> str:
        if code and code.isdigit() and int(code) in self.items_by_id:
            return self.items_by_id[int(code)][1]
        return self.items.get(code or "", code or "?")

    def name(self, pid: int | None) -> str:
        return self.players[pid].name if pid in self.players else f"#{pid}"


def _admin_ids() -> set[int]:
    try:
        return set(settings.admin_ids)
    except Exception:  # noqa: BLE001
        return set()


def load(session: Session, days: int = 30, include_admins: bool = False,
         now: datetime | None = None, history_days: int | None = None) -> Dataset:
    """Charge la période `days` (+ `history_days` de journal si une analyse
    regarde plus loin, ex. la rétention ou le temps par zone)."""
    from app.infrastructure.encounters.farm_zone_loader import list_zones

    now = now or datetime.now(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    reach = max(days, history_days or 0) + 1
    lo = utc_naive(now) - timedelta(days=reach)

    admins = _admin_ids()
    players: dict[int, PlayerInfo] = {}
    rows = session.execute(
        select(PlayerModel, PlayerProgressionModel, PlayerResourceModel)
        .join(PlayerProgressionModel, PlayerProgressionModel.player_id == PlayerModel.id, isouter=True)
        .join(PlayerResourceModel, PlayerResourceModel.player_id == PlayerModel.id, isouter=True)
    ).all()
    for p, prog, res in rows:
        is_admin = int(p.discord_id) in admins
        if is_admin and not include_admins:
            continue
        players[p.id] = PlayerInfo(
            id=p.id, discord_id=int(p.discord_id), name=p.display_name or p.username or f"#{p.id}",
            created_at=p.created_at, last_seen_at=getattr(p, "last_seen_at", None), is_admin=is_admin,
            level=prog.level if prog else 1, xp=prog.xp if prog else 0, gold=res.gold if res else 0,
            stat_points=prog.stat_points if prog else 0, skill_points=prog.skill_points if prog else 0,
            points=(prog.points_attack, prog.points_defense, prog.points_max_hp) if prog else (0, 0, 0),
        )

    events = []
    cols = (GameEventModel.id, GameEventModel.at, GameEventModel.kind, GameEventModel.player_id, GameEventModel.zone,
            GameEventModel.ref, GameEventModel.gold, GameEventModel.xp, GameEventModel.qty, GameEventModel.data)
    q = (select(*cols).where(GameEventModel.at >= lo, GameEventModel.kind != kinds.FLEE)
         .order_by(GameEventModel.at, GameEventModel.id))
    for r in session.execute(q):
        if r.player_id is not None and r.player_id not in players:
            continue                          # admin exclu, ou joueur supprimé
        try:
            data = json.loads(r.data) if r.data else {}
        except ValueError:
            data = {}
        events.append(Event(r.id, r.at, r.kind, r.player_id, r.zone, r.ref, int(r.gold or 0), int(r.xp or 0),
                            int(r.qty or 0), data))

    hour = func.strftime("%Y-%m-%d %H:00:00", GameEventModel.at)
    flees = {}
    for zone, h, n in session.execute(
            select(GameEventModel.zone, hour, func.count()).where(GameEventModel.at >= lo, GameEventModel.kind == kinds.FLEE)
            .group_by(GameEventModel.zone, hour)).all():
        flees[(zone or "", datetime.strptime(h, "%Y-%m-%d %H:%M:%S"))] = int(n)
    last_event_id = session.execute(select(func.max(GameEventModel.id))).scalar() or 0

    snap_lo = to_local(now).date() - timedelta(days=reach)
    snapshots = []
    for s in session.execute(select(PlayerDailySnapshotModel).where(PlayerDailySnapshotModel.day >= snap_lo)).scalars():
        if s.player_id not in players:
            continue
        try:
            data = json.loads(s.data) if s.data else {}
        except ValueError:
            data = {}
        snapshots.append(Snapshot(s.day, s.player_id, s.taken_at, s.level, s.xp_total, s.gold, s.power,
                                  s.rank or "", s.kills, s.combats, s.wins, s.gold_earned, data))

    zones = {str(z["channel_id"]): (z["name"], z.get("rank", "")) for z in list_zones() if z.get("channel_id")}
    mobs = {m.code: {"name": m.name, "family": m.family, "element": m.element, "gear": m.gear_item_code}
            for m in session.execute(select(MobDefinitionModel)).scalars()}
    items, items_by_id = {}, {}
    for it in session.execute(select(ItemDefinitionModel)).scalars():
        items[it.code] = it.name
        items_by_id[it.id] = (it.code, it.name)
    return Dataset(now, days, include_admins, players, events, snapshots, zones, mobs, items, items_by_id,
                   flees=flees, last_event_id=last_event_id)


_CACHE: dict[tuple, tuple[float, Dataset]] = {}
CACHE_SECONDS = 90


def cached(session: Session, days: int = 30, include_admins: bool = False, fresh: bool = False,
           history_days: int = 60) -> Dataset:
    """`load` gardé 90 s : passer d'une page à l'autre ne recharge pas tout
    (« Actualiser » force une relecture)."""
    import time

    key = (days, include_admins, history_days)
    hit = _CACHE.get(key)
    if hit and not fresh and time.monotonic() - hit[0] < CACHE_SECONDS:
        return hit[1]
    ds = load(session, days=days, include_admins=include_admins, history_days=history_days)
    _CACHE.clear() if len(_CACHE) > 8 else None
    _CACHE[key] = (time.monotonic(), ds)
    return ds


def clear_cache() -> None:
    _CACHE.clear()
