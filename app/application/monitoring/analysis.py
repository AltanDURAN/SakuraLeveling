"""Analyses des pages de surveillance : chaque fonction rend un dictionnaire
prêt pour le gabarit (les graphiques sont dessinés côté site, à partir de
ces séries)."""

from __future__ import annotations

import json
import statistics
from collections import Counter, defaultdict
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.application.monitoring.dataset import Dataset, Event, to_local
from app.application.monitoring.players import PlayerRow, build_rows, content_end_level
from app.domain.services.gear_service import RARITY_LABELS
from app.domain.services.monitoring import activity, kinds, progression as prog
from app.domain.services.monitoring.stats import gini, median, percentile, percentile_rank, share
from app.domain.services.pacing_service import WEEKDAYS

CONTENT = Path(__file__).resolve().parents[2] / "infrastructure" / "content"
RARITY_KEYS = ("common", "uncommon", "rare", "epic", "legendary", "mythic")
STAT_LABELS = ("Attaque", "Défense", "PV")


# ================================================================ référence
@lru_cache(maxsize=1)
def quest_xp_at_20() -> float:
    """XP de quêtes par jour d'un joueur régulier, au niveau 20 (mêmes
    hypothèses que `scripts/simulate_season` : 2 quotidiennes sur 3, 2
    hebdomadaires sur 3)."""
    def mean_xp(name: str) -> float:
        try:
            data = json.loads((CONTENT / name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return 0.0
        quests = data if isinstance(data, list) else data.get("quests", [])
        values = [q.get("reward_xp", 0) for q in quests if isinstance(q, dict)]
        return statistics.mean(values) if values else 0.0
    return 2 * mean_xp("daily_quests.json") + 2 * mean_xp("weekly_quests.json") / 7


@lru_cache(maxsize=4)
def reference_curve(minutes_per_day: int, days: int = 1200) -> tuple[int, ...]:
    return tuple(prog.reference_curve(minutes_per_day, days, quest_xp_at_20=quest_xp_at_20()))


def design_days(level: int = prog.LEVEL_CAP, minutes_per_day: int = 60) -> int | None:
    return prog.day_reaching(reference_curve(minutes_per_day), level)


# ================================================================== outils
def _day(e: Event) -> date:
    return e.local.date()


def daily_series(ds: Dataset, events: list[Event], value=lambda e: 1, days: int | None = None) -> list[float]:
    days_ = ds.day_list(days)
    index = {d: i for i, d in enumerate(days_)}
    out = [0.0] * len(days_)
    for e in events:
        i = index.get(_day(e))
        if i is not None:
            out[i] += value(e)
    return out


def encounters(ds: Dataset, days: float | None = None) -> dict[str, list[Event]]:
    out: dict[str, list[Event]] = defaultdict(list)
    for e in ds.of_kind(kinds.COMBAT, days=days):
        out[e.data.get("enc") or f"solo:{e.id}"].append(e)
    return out


def dau_series(ds: Dataset, days: int | None = None) -> list[int]:
    days_ = ds.day_list(days)
    index = {d: i for i, d in enumerate(days_)}
    seen: list[set[int]] = [set() for _ in days_]
    for pid in ds.players:
        for d in ds.active_days(pid):
            i = index.get(d)
            if i is not None:
                seen[i].add(pid)
    return [len(s) for s in seen]


def _delta(current: float, previous: float) -> float | None:
    if not previous:
        return None
    return 100 * (current - previous) / previous


def kpi(label: str, value, previous=None, unit: str = "", good_up: bool = True, spark=None,
        hint: str = "", fmt: str = "int") -> dict:
    return {"label": label, "value": value, "previous": previous,
            "delta": _delta(value, previous) if previous is not None and isinstance(value, (int, float)) else None,
            "unit": unit, "good_up": good_up, "spark": spark or [], "hint": hint, "fmt": fmt}


# ================================================================ économie
def gold_flows(ds: Dataset, days: int | None = None) -> dict:
    """Or créé / détruit / échangé par jour et par source (journal `gold`)."""
    days_ = ds.day_list(days)
    index = {d: i for i, d in enumerate(days_)}
    creation = {s: [0] * len(days_) for s in kinds.CREATION_ORDER}
    destruction = {s: [0] * len(days_) for s in kinds.DESTRUCTION_ORDER}
    transfer = defaultdict(int)
    admin = [0] * len(days_)
    other = [0] * len(days_)
    window = ds.of_kind(kinds.GOLD, days=days if days is not None else ds.days)
    for e in window:
        i = index.get(_day(e))
        if i is None:
            continue
        flow = kinds.flow_of(e.ref, e.gold)
        if flow == kinds.CREATION:
            creation.setdefault(e.ref, [0] * len(days_))[i] += e.gold
        elif flow == kinds.DESTRUCTION:
            destruction.setdefault(e.ref, [0] * len(days_))[i] += -e.gold
        elif flow == kinds.TRANSFER_FLOW:
            transfer[e.ref] += abs(e.gold)
            if e.ref == "brocante":       # acheteur −prix, vendeur +prix − taxe
                destruction["taxe"][i] += -e.gold
        elif flow == kinds.ADMIN:
            admin[i] += e.gold
        else:
            other[i] += e.gold
    # « taxe » a accumulé −(somme des mouvements de brocante) : c'est la taxe.
    created = [sum(v[i] for v in creation.values()) for i in range(len(days_))]
    destroyed = [sum(v[i] for v in destruction.values()) for i in range(len(days_))]
    return {"days": days_, "creation": creation, "destruction": destruction, "created": created,
            "destroyed": destroyed, "transfer": dict(transfer), "admin": admin, "other": other}


def money_supply(ds: Dataset, days: int | None = None) -> list[int]:
    """Or total des joueurs à la fin de chaque jour (photos ; aujourd'hui = réel)."""
    days_ = ds.day_list(days)
    out = []
    for d in days_:
        if d == ds.today:
            out.append(sum(p.gold for p in ds.players.values()))
            continue
        total = 0
        for pid in ds.players:
            s = ds.snapshot_on(pid, d)
            total += s.gold if s else 0
        out.append(total)
    return out


# ================================================================== pages
def overview(ds: Dataset) -> dict:
    rows = build_rows(ds)
    dau = dau_series(ds)
    active_24 = len(ds.active_in(1))
    active_prev_24 = len(ds.active_in(1, until=ds.now_naive - timedelta(days=1)))
    active_7 = len(ds.active_in(7))
    active_prev_7 = len(ds.active_in(7, until=ds.now_naive - timedelta(days=7)))
    week_ago = ds.now_naive - timedelta(days=7)
    new_7 = sum(1 for p in ds.players.values() if p.created_at and p.created_at >= week_ago)
    new_prev = sum(1 for p in ds.players.values()
                   if p.created_at and week_ago - timedelta(days=7) <= p.created_at < week_ago)
    enc = encounters(ds)
    enc_days = Counter(to_local(min(e.at for e in evs)).date() for evs in enc.values())
    enc_series = [enc_days.get(d, 0) for d in ds.day_list()]
    day_ago = ds.now_naive - timedelta(days=1)
    starts = [min(e.at for e in evs) for evs in enc.values()]
    enc_24 = sum(1 for t in starts if t >= day_ago)
    enc_prev_24 = sum(1 for t in starts if day_ago - timedelta(days=1) <= t < day_ago)
    play_7 = [r.play_min_7d for r in rows if r.play_min_7d > 0]
    player_days_7 = sum(r.active_days_7d for r in rows)
    flows = gold_flows(ds)
    net = [c - d for c, d in zip(flows["created"], flows["destroyed"])]
    end_level = content_end_level(ds)
    ahead = sorted((r for r in rows if r.days_to_content_end is not None and r.level < end_level),
                   key=lambda r: r.days_to_content_end)
    reached = sum(1 for r in rows if r.level >= end_level)
    caps = [r.days_to_cap for r in rows if r.days_to_cap is not None and r.active_days_7d >= 2]
    grid = activity.heatmap(t.local for t in ds.events if t.kind in kinds.ACTIVITY_KINDS and ds.in_window(t))
    busy, quiet = activity.busy_and_quiet(activity.hour_profile(grid))
    mob_share = mob_table(ds)[:6]
    return {
        "kpis": [
            kpi("Joueurs actifs (24 h)", active_24, active_prev_24, spark=dau[-15:-1],
                hint="Comparé aux 24 h d'avant ; la courbe montre les 14 derniers jours complets."),
            kpi("Joueurs actifs (7 j)", active_7, active_prev_7),
            kpi("Nouveaux joueurs (7 j)", new_7, new_prev),
            kpi("Temps de jeu / joueur / jour", (sum(play_7) / player_days_7) if player_days_7 else 0, unit="min",
                hint="Moyenne des 7 derniers jours, les jours où le joueur a joué.", fmt="min"),
            kpi("Combats (24 h)", enc_24, enc_prev_24, spark=enc_series[-15:-1]),
            kpi("Or créé net (7 j)", sum(net[-7:]), sum(net[-14:-7]) if len(net) >= 14 else None,
                good_up=False, hint="Or créé moins or détruit : ce qui gonfle la masse d'or."),
        ],
        "journal_start": to_local(ds.journal_start) if ds.journal_start else None,
        "season": ds.season,
        "journal_young": ds.journal_start is None or (ds.now_naive - ds.journal_start).days < 7,
        "hero": {"value": active_24, "label": "joueurs actifs ces dernières 24 h",
                 "sub": f"{len(ds.players)} joueurs inscrits · {active_7} actifs cette semaine"},
        "dau": dau,
        "days": ds.day_list(),
        "grid": grid, "busy": busy[:2], "quiet": quiet[:2],
        "flows": flows,
        "net": net,
        "top_players": sorted(rows, key=lambda r: -r.investment)[:6],
        "mobs": mob_share,
        "content_end": {"level": end_level, "player": ahead[0] if ahead else None, "reached": reached},
        "median_cap_days": median(caps) if caps else None,
        "design_cap_days": design_days(),
        "pace_players": len(caps),
    }


def activity_page(ds: Dataset) -> dict:
    rows = build_rows(ds)
    days_ = ds.day_list()
    dau = dau_series(ds)
    active_map = {pid: ds.active_days(pid) for pid in ds.players}
    wau = activity.rolling_active(active_map, days_, 7)
    mau = activity.rolling_active(active_map, days_, 30)
    acts = [e for e in ds.events if e.kind in kinds.ACTIVITY_KINDS and ds.in_window(e)]
    grid = activity.heatmap(e.local for e in acts)
    profile = activity.hour_profile(grid)
    busy, quiet = activity.busy_and_quiet(profile)
    by_weekday = [sum(row) for row in grid]
    # Monstres repartis sans combattant, par heure : où la zone tourne à vide.
    enc_hours = Counter(to_local(min(e.at for e in evs)).hour for evs in encounters(ds).values())
    flee_hours = Counter()
    for (_, at), n in ds.flees.items():
        if at >= ds.start:
            flee_hours[to_local(at).hour] += n
    spawn_fill = []
    for h in range(24):
        total = enc_hours.get(h, 0) + flee_hours.get(h, 0)
        spawn_fill.append({"hour": h, "fought": enc_hours.get(h, 0), "fled": flee_hours.get(h, 0),
                           "fill": 100 * enc_hours.get(h, 0) / total if total else None})
    commands = Counter()
    buttons = 0
    for e in ds.of_kind(kinds.INTERACTION):
        ref = e.ref or "?"
        if ref.startswith("bouton"):
            buttons += 1
        else:
            commands[f"/{ref}"] += 1
    # Temps de jeu : moyenne par jour JOUÉ, par joueur.
    per_player = [r.play_min / r.active_days for r in rows if r.active_days]
    bins = [(0, 15), (15, 30), (30, 60), (60, 120), (120, 240), (240, 10_000)]
    hist = [sum(1 for v in per_player if lo <= v < hi) for lo, hi in bins]
    sessions = [s for pid in ds.players for s in ds.sessions(pid) if s.end >= ds.start]
    cohorts = activity.retention(ds.arrivals(), active_map, ds.today)
    suggestions = _suggestions(busy, quiet, spawn_fill, by_weekday)
    return {
        "days": days_, "dau": dau, "wau": wau, "mau": mau,
        "stickiness": 100 * statistics.mean(dau[-7:]) / mau[-1] if mau and mau[-1] else None,
        "grid": grid, "profile": profile, "busy": busy, "quiet": quiet, "hours": [f"{h}h" for h in range(24)],
        "weekdays": list(zip(WEEKDAYS, by_weekday)),
        "spawn_fill": spawn_fill,
        "commands": commands.most_common(15), "buttons": buttons,
        "playtime_bins": list(zip(["< 15 min", "15–30 min", "30 min–1 h", "1–2 h", "2–4 h", "4 h et +"], hist)),
        "median_session": median([s.minutes for s in sessions]) if sessions else 0,
        "sessions_per_day": (len(sessions) / sum(r.active_days for r in rows)) if any(r.active_days for r in rows) else 0,
        "total_hours": sum(s.minutes for s in sessions) / 60,
        "cohorts": cohorts[-10:],
        "suggestions": suggestions,
        "top_time": sorted(rows, key=lambda r: -r.play_min)[:10],
    }


def _suggestions(busy, quiet, spawn_fill, by_weekday) -> list[dict]:
    out = []
    if busy:
        b = busy[0]
        out.append({"icon": "🔥", "title": f"Pic d'activité : {b.label}",
                    "text": "Le meilleur moment pour un événement (coffre, forge sacrée), une annonce ou le raid : "
                            "c'est là que le plus de joueurs le verront.",
                    "link": ("/admin/events", "Événements")})
    for q in quiet[:2]:
        hours = {h % 24 for h in range(q.start, q.end if q.end > q.start else q.end + 24)}
        fled = [s for s in spawn_fill if s["hour"] in hours]
        total = sum(s["fought"] + s["fled"] for s in fled)
        empty = sum(s["fled"] for s in fled)
        rate = f" — {100 * empty / total:.0f} % des monstres repartent sans combattant" if total else ""
        out.append({"icon": "🌙", "title": f"Heures creuses : {q.label}{rate}",
                    "text": "Soit des heures calmes (moins de monstres, Monde › Rythme), soit une raison de venir : "
                            "un monstre rare ou des gains bonus à ces heures-là.",
                    "link": ("/admin/pacing", "Rythme")})
    if any(by_weekday):
        best = max(range(7), key=lambda i: by_weekday[i])
        worst = min(range(7), key=lambda i: by_weekday[i])
        if by_weekday[best] > 1.4 * max(1, by_weekday[worst]):
            out.append({"icon": "📅", "title": f"Le {WEEKDAYS[best]} est le jour le plus actif, le {WEEKDAYS[worst]} le plus calme",
                        "text": f"{by_weekday[best] / max(1, by_weekday[worst]):.1f}× plus d'actions. Un rendez-vous "
                                f"hebdomadaire le {WEEKDAYS[worst]} peut lisser la semaine.".replace(".", ",", 1),
                        "link": ("/admin/pacing", "Raid")})
    return out


def mob_table(ds: Dataset) -> list[dict]:
    enc = encounters(ds)
    stats: dict[str, dict] = defaultdict(lambda: {"fights": 0, "wins": 0, "participants": 0, "deaths": 0,
                                                  "turns": [], "players": set(), "credited": 0, "groups": []})
    total_kills = 0
    for evs in enc.values():
        first = evs[0]
        won = any(e.data.get("res") in ("win", "death") for e in evs)
        for code in first.data.get("mobs") or [first.ref]:
            s = stats[code]
            s["fights"] += 1
            s["groups"].append(len(evs))
            if won:
                s["wins"] += 1
                s["turns"].append(first.data.get("turns", 0))
                total_kills += 1
            for e in evs:
                s["participants"] += 1
                s["deaths"] += e.data.get("res") == "death"
                s["credited"] += e.data.get("res") == "win"
                s["players"].add(e.player_id)
    out = []
    for code, s in stats.items():
        info = ds.mobs.get(code) or {}
        out.append({
            "code": code, "name": ds.mob_name(code), "family": info.get("family", ""),
            "kills": s["wins"], "share": 100 * share(s["wins"], total_kills), "fights": s["fights"],
            "credited": s["credited"],
            "win_pct": 100 * share(s["wins"], s["fights"]), "death_pct": 100 * share(s["deaths"], s["participants"]),
            "turns": statistics.mean(s["turns"]) if s["turns"] else 0, "players": len(s["players"]),
            "group": statistics.mean(s["groups"]) if s["groups"] else 0,
        })
    return sorted(out, key=lambda r: -r["kills"])


def combat_page(ds: Dataset) -> dict:
    enc = encounters(ds)
    parts = ds.of_kind(kinds.COMBAT)
    flees = {k: n for k, n in ds.flees.items() if k[1] >= ds.start}
    n_flees = sum(flees.values())
    won = [evs for evs in enc.values() if any(e.data.get("res") in ("win", "death") for e in evs)]
    sizes = Counter(min(len(evs), 5) for evs in enc.values())
    zones: dict[str, dict] = defaultdict(lambda: {"fights": 0, "wins": 0, "parts": 0, "deaths": 0, "flees": 0,
                                                  "players": set()})
    for evs in enc.values():
        z = zones[evs[0].zone or ""]
        z["fights"] += 1
        z["wins"] += any(e.data.get("res") in ("win", "death") for e in evs)
        for e in evs:
            z["parts"] += 1
            z["deaths"] += e.data.get("res") == "death"
            z["players"].add(e.player_id)
    for (zone, _), n in flees.items():
        zones[zone or ""]["flees"] += n
    zone_rows = sorted(({
        "name": ds.zone_name(code), "rank": ds.zone_rank(code), "fights": z["fights"],
        "win_pct": 100 * share(z["wins"], z["fights"]), "death_pct": 100 * share(z["deaths"], z["parts"]),
        "flee_pct": 100 * share(z["flees"], z["flees"] + z["fights"]), "players": len(z["players"]),
        "group": share(z["parts"], z["fights"]),
    } for code, z in zones.items()), key=lambda r: (kinds.RANK_ORDER.index(r["rank"]) if r["rank"] in kinds.RANK_ORDER else 99))
    lunar = defaultdict(lambda: [0, 0])
    for evs in enc.values():
        key = evs[0].data.get("lune") or "normal"
        lunar[key][0] += 1
        lunar[key][1] += any(e.data.get("res") in ("win", "death") for e in evs)
    drops = Counter(e.data.get("rarity", "common") for e in ds.of_kind(kinds.GEAR_DROP))
    turns = [evs[0].data.get("turns", 0) for evs in won]
    daily = Counter(to_local(min(e.at for e in evs)).date() for evs in enc.values())
    return {
        "kpis": [
            kpi("Combats", len(enc)),
            kpi("Victoires", 100 * share(len(won), len(enc)), unit="%", fmt="pct"),
            kpi("Participants tués", 100 * share(sum(e.data.get("res") == "death" for e in parts), len(parts)),
                unit="%", good_up=False, fmt="pct"),
            kpi("Durée moyenne", statistics.mean(turns) if turns else 0, unit="actions", fmt="dec"),
            kpi("Joueurs par combat", share(len(parts), len(enc)), fmt="dec"),
            kpi("Monstres ignorés", 100 * share(n_flees, n_flees + len(enc)), unit="%", good_up=False,
                fmt="pct", hint="Repartis sans combattant."),
        ],
        "mobs": mob_table(ds),
        "zones": zone_rows,
        "sizes": [(f"{n} joueur{'s' if n > 1 else ''}" if n < 5 else "5 et +", sizes.get(n, 0)) for n in range(1, 6)],
        "lunar": [(k, v[0], 100 * share(v[1], v[0])) for k, v in lunar.items()],
        "drops": [(RARITY_LABELS.get(r, r), drops.get(r, 0)) for r in RARITY_KEYS],
        "days": ds.day_list(),
        "daily": [daily.get(d, 0) for d in ds.day_list()],
    }


def economy_page(ds: Dataset) -> dict:
    flows = gold_flows(ds)
    supply = money_supply(ds)
    golds = [p.gold for p in ds.players.values()]
    created = sum(flows["created"])
    destroyed = sum(flows["destroyed"])
    sources = sorted(((s, sum(v)) for s, v in flows["creation"].items() if sum(v)), key=lambda x: -x[1])
    sinks = sorted(((s, sum(v)) for s, v in flows["destruction"].items() if sum(v)), key=lambda x: -x[1])
    shop = defaultdict(lambda: [0, 0, set()])
    for e in ds.of_kind(kinds.SHOP_BUY):
        shop[e.ref][0] += e.qty or 1
        shop[e.ref][1] += -e.gold
        shop[e.ref][2].add(e.player_id)
    market = defaultdict(lambda: [0, 0])
    for e in ds.of_kind(kinds.MARKET_SALE):
        market[e.ref][0] += 1
        market[e.ref][1] += e.gold
    ordered = sorted(golds, reverse=True)
    deciles = []
    if ordered and sum(ordered):
        n = len(ordered)
        for k in range(10):
            part = ordered[k * n // 10:(k + 1) * n // 10]
            deciles.append(100 * sum(part) / sum(ordered))
    # Or gagné par heure de jeu, par tranche de niveau, contre le design
    # (3 or × niveau par monstre, un combat toutes les 3 min).
    rows = build_rows(ds)
    bands = []
    for lo in range(1, 101, 10):
        rates = [r.gold_per_hour for r in rows if lo <= r.level < lo + 10 and r.gold_per_hour]
        if rates:
            bands.append({"band": f"{lo}–{lo + 9}", "measured": median(rates), "design": 3 * (lo + 4.5) * 20,
                          "players": len(rates)})
    return {
        "kpis": [
            kpi("Masse d'or", supply[-1] if supply else 0, supply[-8] if len(supply) >= 8 else None,
                good_up=False, hint="Or détenu par tous les joueurs, contre il y a 7 jours."),
            kpi("Or créé", created, hint="Combats, quêtes, daily, raid, tour, défis, événements."),
            kpi("Or détruit", destroyed, hint="Sorn, fusion, potions, voyante, offrande, taxe de brocante."),
            kpi("Détruit / créé", 100 * share(destroyed, created), unit="%", fmt="pct",
                hint="Sous 100 %, la masse d'or grossit."),
            kpi("Or médian par joueur", median(golds) if golds else 0),
            kpi("Concentration (Gini)", gini(golds), fmt="gini", good_up=False,
                hint="0 = tout le monde a pareil, 1 = un seul a tout."),
        ],
        "flows": flows,
        "net": [c - d for c, d in zip(flows["created"], flows["destroyed"])],
        "supply": supply,
        "sources": [(kinds.gold_source(s), v, 100 * share(v, created)) for s, v in sources],
        "sinks": [(kinds.gold_source(s) if s != "taxe" else kinds.GoldSource("taxe", "Taxe de brocante", "🏷️"),
                   v, 100 * share(v, destroyed)) for s, v in sinks],
        "transfer": flows["transfer"],
        "admin": sum(flows["admin"]),
        "other": sum(flows["other"]),
        "shop": sorted(((ds.item_name(code), v[0], v[1], len(v[2])) for code, v in shop.items()), key=lambda x: -x[2])[:15],
        "market": sorted(((ds.item_name(code), v[0], v[1]) for code, v in market.items()), key=lambda x: -x[2])[:10],
        "deciles": deciles,
        "bands": bands,
        "richest": sorted(rows, key=lambda r: -r.gold)[:8],
    }


def meta_page(ds: Dataset, session: Session) -> dict:
    from app.infrastructure.db.models.element_affinity_model import PlayerElementAffinityModel
    from app.infrastructure.db.models.player_skill_allocation_model import PlayerSkillAllocationModel
    from app.infrastructure.skill_tree.skill_tree_loader import get_definition
    from app.shared.enums import ELEMENT_EMOJIS, ELEMENT_LABELS

    rows = {r.pid: r for r in build_rows(ds)}
    snaps = [s for pid in ds.players if (s := ds.latest_snapshot(pid)) is not None]
    equipped = [s for s in snaps if s.data.get("gear")]
    worn = Counter()
    rarity = Counter()
    for s in equipped:
        for code, r in {tuple(g) for g in s.data["gear"]}:
            worn[code] += 1
            rarity[r] += 1
    specs = Counter((s.data.get("spec") or "Aucune") for s in snaps)
    classes = Counter(c for s in snaps for c in s.data.get("classes", []))
    from app.domain.services.combat_passives import DEFAULT_TACTIC, TACTICS
    from app.domain.services.set_bonus_service import panoplie_type

    tactics = Counter(TACTICS.get(s.data.get("tactic") or DEFAULT_TACTIC, (s.data.get("tactic"), ""))[0] for s in snaps)
    panoplies = Counter(f"{(pt := panoplie_type(s.data.get('panoplie'))).emoji} {pt.label}" for s in snaps)
    splits = []
    dominant = Counter()
    for s in snaps:
        pts = s.data.get("pts") or [0, 0, 0]
        total = sum(pts)
        if total >= 5:
            splits.append([100 * p / total for p in pts])
            top = max(range(3), key=lambda i: pts[i])
            if pts[top] / total > 0.8:
                dominant[STAT_LABELS[top]] += 1
    avg_split = [statistics.mean(col) for col in zip(*splits)] if splits else [0, 0, 0]
    by_role = defaultdict(lambda: {"players": 0, "combats": 0, "wins": 0, "gold": 0, "minutes": 0.0})
    for r in rows.values():
        if r.combats == 0:
            continue
        g = by_role[r.spec or "Aucune"]
        g["players"] += 1
        g["combats"] += r.combats
        g["wins"] += r.wins
        g["gold"] += r.gold_created
        g["minutes"] += r.play_min
    definition = get_definition()
    nodes = Counter(dict(session.execute(
        select(PlayerSkillAllocationModel.skill_code, func.count(PlayerSkillAllocationModel.player_id))
        .where(PlayerSkillAllocationModel.level > 0,
               PlayerSkillAllocationModel.player_id.in_(list(ds.players)))
        .group_by(PlayerSkillAllocationModel.skill_code)).all()))
    with_tree = session.execute(select(func.count(func.distinct(PlayerSkillAllocationModel.player_id)))
                                .where(PlayerSkillAllocationModel.level > 0,
                                       PlayerSkillAllocationModel.player_id.in_(list(ds.players)))).scalar() or 0
    node_rows = []
    names = Counter(node.name for node in definition.skills.values())
    for code, n in nodes.most_common(15):
        node = definition.get(code)
        label = f"{node.icon} {node.name}" if node else code
        if node and names[node.name] > 1:          # plusieurs cases du même nom
            label += f" ({code})"
        node_rows.append((label, n, 100 * share(n, with_tree)))
    aff = session.execute(
        select(PlayerElementAffinityModel.element, func.avg(PlayerElementAffinityModel.value),
               func.sum(case((PlayerElementAffinityModel.revealed.is_(True), 1), else_=0)))
        .where(PlayerElementAffinityModel.player_id.in_(list(ds.players)))
        .group_by(PlayerElementAffinityModel.element)).all()
    return {
        "equipped_players": len(equipped),
        "worn": [(ds.item_name(code), n, 100 * share(n, len(equipped))) for code, n in worn.most_common(15)],
        "rarity": [(RARITY_LABELS.get(r, r), rarity.get(r, 0)) for r in RARITY_KEYS],
        "specs": specs.most_common(),
        "specialized": sum(n for k, n in specs.items() if k != "Aucune"),
        "classes": classes.most_common(12),
        "tactics": tactics.most_common(),
        "panoplies": panoplies.most_common(),
        "split": avg_split,
        "dominant": dominant.most_common(),
        "split_players": len(splits),
        "roles": [{"spec": k, **v, "win_pct": 100 * share(v["wins"], v["combats"]),
                   "gold_h": v["gold"] / (v["minutes"] / 60) if v["minutes"] >= 30 else None}
                  for k, v in sorted(by_role.items(), key=lambda kv: -kv[1]["players"])],
        "nodes": node_rows,
        "tree_players": with_tree,
        "affinities": [(f"{ELEMENT_EMOJIS.get(el, '')} {ELEMENT_LABELS.get(el, el)}", float(avg or 0), int(rev or 0))
                       for el, avg, rev in aff],
    }


def zone_times(ds: Dataset, session: Session) -> list[dict]:
    """Temps passé dans chaque zone avant d'atteindre la suivante : de son
    premier combat dans la zone (ou de son arrivée pour la première) à sa
    promotion au rang suivant ou son premier combat dans la zone suivante."""
    from app.infrastructure.db.models.monitoring_model import GameEventModel

    rank_of = {code: rank for code, (_, rank) in ds.zones.items()}
    first: dict[int, dict[str, object]] = defaultdict(dict)
    combats: dict[int, Counter] = defaultdict(Counter)
    q = (select(GameEventModel.player_id, GameEventModel.zone, func.min(GameEventModel.at), func.count())
         .where(GameEventModel.kind == kinds.COMBAT, GameEventModel.player_id.in_(list(ds.players)))
         .group_by(GameEventModel.player_id, GameEventModel.zone))
    for pid, zone, at, n in session.execute(q).all():
        rank = rank_of.get(zone or "")
        if rank:
            prev = first[pid].get(rank)
            first[pid][rank] = at if prev is None or at < prev else prev
            combats[pid][rank] += n
    q = (select(GameEventModel.player_id, GameEventModel.ref, func.min(GameEventModel.at))
         .where(GameEventModel.kind == kinds.RANK_UP, GameEventModel.player_id.in_(list(ds.players)))
         .group_by(GameEventModel.player_id, GameEventModel.ref))
    promoted: dict[int, dict[str, object]] = defaultdict(dict)
    for pid, rank, at in session.execute(q).all():
        promoted[pid][rank] = at
    open_ranks = [r for r in kinds.RANK_ORDER if r in set(rank_of.values())]
    ref = reference_curve(60)
    out = []
    for i, rank in enumerate(open_ranks):
        nxt = open_ranks[i + 1] if i + 1 < len(open_ranks) else None
        done, ongoing, fights = [], [], []
        for pid, info in ds.players.items():
            start = first[pid].get(rank)
            if rank == open_ranks[0] and info.started_at is not None:
                start = min(filter(None, (start, info.started_at)))
            if start is None:
                continue
            ends = [t for t in (first[pid].get(nxt) if nxt else None, promoted[pid].get(nxt) if nxt else None) if t]
            if ends:
                done.append((min(ends) - start).total_seconds() / 86400)
                fights.append(combats[pid][rank])
            else:
                ongoing.append((ds.now_naive - start).total_seconds() / 86400)
        low, high = prog.ZONE_LEVELS.get(rank, (1, 100))
        d_lo, d_hi = prog.day_reaching(ref, low), prog.day_reaching(ref, high + 1 if high < 100 else 100)
        out.append({"rank": rank, "name": next((n for c, (n, r) in ds.zones.items() if r == rank), rank),
                    "levels": f"{low}–{high}", "done": len(done), "ongoing": len(ongoing),
                    "median_days": median(done) if done else None,
                    "p25": percentile(done, 25) if done else None, "p75": percentile(done, 75) if done else None,
                    "median_fights": median(fights) if fights else None,
                    "ongoing_days": median(ongoing) if ongoing else None,
                    "design_days": (d_hi - d_lo) if d_lo and d_hi else None, "next": nxt})
    return out


def progression_page(ds: Dataset, session: Session) -> dict:
    rows = build_rows(ds)
    levels = [r.level for r in rows]
    hist = [(f"{lo}–{lo + 4}", sum(1 for v in levels if lo <= v <= lo + 4)) for lo in range(1, 101, 5)]
    while hist and hist[-1][1] == 0 and len(hist) > 4:
        hist.pop()
    ranks = Counter((r.rank or "?") for r in rows)
    # Courbes : niveau selon les jours depuis l'arrivée, contre le design.
    curves = []
    for pid, info in ds.players.items():
        if info.started_at is None:
            continue
        start = to_local(info.started_at).date()
        pts = [((s.day - start).days, s.level) for s in ds.snapshots_by_player.get(pid, ())]
        pts.append(((ds.today - start).days, info.level))
        pts = sorted({d: lv for d, lv in pts if d >= 0}.items())
        if pts:
            curves.append({"pid": pid, "name": info.name, "points": pts})
    horizon = max((p[-1][0] for p in (c["points"] for c in curves)), default=30)
    horizon = max(14, min(horizon, 400))
    med = []
    for d in range(horizon + 1):
        vals = []
        for c in curves:
            known = [lv for day, lv in c["points"] if day <= d]
            if known and c["points"][-1][0] >= d:
                vals.append(known[-1])
        med.append(median(vals) if len(vals) >= 2 else None)
    filled = []
    for c in curves:
        vals: list[float | None] = []
        known = dict(c["points"])
        last_day = c["points"][-1][0]
        cur = None
        for d in range(horizon + 1):
            cur = known.get(d, cur)
            vals.append(cur if d <= last_day else None)
        filled.append({"name": c["name"], "values": vals, "faint": True})
    caps = sorted((r for r in rows if r.days_to_cap is not None and r.active_days_7d >= 1), key=lambda r: r.days_to_cap)
    end_level = content_end_level(ds)
    stuck = []
    for r in rows:
        snaps = [s for s in ds.snapshots_by_player.get(r.pid, ()) if s.day >= ds.today - timedelta(days=14)]
        same = [s for s in snaps if s.level == r.level]
        played = len([d for d in ds.active_days(r.pid) if any(s.day == d for s in same)])
        if len(same) >= 5 and played >= 3 and r.level < end_level:
            stuck.append((r, len(same), played))
    towers = Counter()
    for pid in ds.players:
        s = ds.latest_snapshot(pid)
        if s and s.data.get("tower"):
            towers[(s.data["tower"] - 1) // 10] += 1
    xp_sources = {"Combats": sum(e.xp for e in ds.of_kind(kinds.COMBAT)),
                  "Quêtes": sum(e.xp for e in ds.of_kind(kinds.QUEST))}
    return {
        "hist": hist,
        "ranks": [(r, ranks.get(r, 0)) for r in kinds.RANK_ORDER if ranks.get(r)] + ([("?", ranks["?"])] if ranks.get("?") else []),
        "curves": filled, "median": med, "horizon": horizon,
        "median_level": median(levels) if levels else 0,
        "ref30": list(reference_curve(30)[:horizon + 1]), "ref60": list(reference_curve(60)[:horizon + 1]),
        "zones": zone_times(ds, session),
        "projections": caps[:15],
        "median_cap": median([r.days_to_cap for r in caps]) if caps else None,
        "design_cap": design_days(), "design_cap_30": design_days(minutes_per_day=30),
        "end_level": end_level,
        "end_reached": sum(1 for r in rows if r.level >= end_level),
        "ahead": sorted((r for r in rows if r.days_to_content_end is not None), key=lambda r: r.days_to_content_end)[:5],
        "stuck": sorted(stuck, key=lambda x: -x[1]),
        "unspent": sorted((r for r in rows if r.unspent >= 5), key=lambda r: -r.unspent)[:12],
        "towers": [(f"{k * 10 + 1}–{k * 10 + 10}", towers[k]) for k in sorted(towers)],
        "xp_sources": xp_sources,
    }


def players_page(ds: Dataset, flagged: dict[int, list[str]] | None = None) -> dict:
    rows = build_rows(ds)
    for r in rows:
        r.flags = (flagged or {}).get(r.pid, [])
    return {"rows": sorted(rows, key=lambda r: -r.investment),
            "segments": {
                "invested": sum(1 for r in rows if r.investment >= 75),
                "new": sum(1 for r in rows if r.created_at and r.created_at >= ds.now_naive - timedelta(days=7)),
                "away": sum(1 for r in rows if r.investment >= 50 and (r.days_since_active or 0) >= 3),
                "flagged": sum(1 for r in rows if r.flags),
            }}


PERCENTILE_METRICS = (
    ("level", "Niveau", lambda r: r.level),
    ("power", "Puissance", lambda r: r.power),
    ("gold", "Or détenu", lambda r: r.gold),
    ("play", "Temps de jeu", lambda r: r.play_min),
    ("days", "Jours joués", lambda r: r.active_days),
    ("combats", "Combats", lambda r: r.combats),
    ("win", "Taux de victoire", lambda r: r.win_rate or 0),
    ("gph", "Or par heure", lambda r: r.gold_per_hour or 0),
)

NOTABLE = {kinds.LEVEL_UP, kinds.RANK_UP, kinds.RANK_TRIAL, kinds.FUSION, kinds.SHOP_BUY, kinds.TRANSFER,
           kinds.MARKET_SALE, kinds.RESPEC, kinds.TUTORIAL, kinds.GEAR_DROP, kinds.SEER, kinds.OFFERING,
           kinds.BREW, kinds.TOWER}


def player_page(ds: Dataset, pid: int) -> dict | None:
    rows = build_rows(ds)
    row = next((r for r in rows if r.pid == pid), None)
    if row is None:
        return None
    others = [r for r in rows if r.play_min > 0 or r.pid == pid]
    ranks = []
    for key, label, fn in PERCENTILE_METRICS:
        values = [fn(r) for r in others]
        ranks.append({"key": key, "label": label, "pct": percentile_rank(values, fn(row)),
                      "value": fn(row), "values": values})
    days_ = ds.day_list()
    mine = {s.day: s for s in ds.snapshots_by_player.get(pid, ())}
    series = {"level": [], "gold": [], "power": []}
    band = {"p25": [], "p50": [], "p75": []}
    for d in days_:
        s = mine.get(d)
        info = ds.players[pid]
        if d == ds.today:
            series["level"].append(info.level)
            series["gold"].append(info.gold)
            series["power"].append(s.power if s else (series["power"][-1] if series["power"] else None))
        else:
            series["level"].append(s.level if s else None)
            series["gold"].append(s.gold if s else None)
            series["power"].append(s.power if s else None)
        lv = [x.level for p in ds.players if (x := ds.snapshot_on(p, d)) is not None and x.day == d]
        band["p25"].append(percentile(lv, 25) if len(lv) >= 3 else None)
        band["p50"].append(median(lv) if len(lv) >= 3 else None)
        band["p75"].append(percentile(lv, 75) if len(lv) >= 3 else None)
    evs = [e for e in ds.by_player.get(pid, ()) if ds.in_window(e)]
    sessions = [s for s in ds.sessions(pid) if s.end >= ds.start]
    per_day = activity.minutes_by_day(sessions, to_local)
    mobs = Counter()
    for e in evs:
        if e.kind == kinds.COMBAT and e.data.get("res") == "win":
            for code in e.data.get("mobs") or [e.ref]:
                mobs[code] += 1
    gold_in = Counter()
    gold_out = Counter()
    for e in evs:
        if e.kind != kinds.GOLD:
            continue
        if e.gold >= 0:
            gold_in[e.ref or "autre"] += e.gold
        else:
            gold_out[e.ref or "autre"] += -e.gold
    timeline = [e for e in evs if e.kind in NOTABLE and not (e.kind == kinds.GEAR_DROP and e.data.get("rarity") in ("common", "uncommon"))]
    timeline += [e for e in evs if e.kind == kinds.GOLD and e.ref in ("admin", "autre")]
    timeline.sort(key=lambda e: e.at, reverse=True)
    snap = ds.latest_snapshot(pid)
    from app.domain.services.combat_passives import DEFAULT_TACTIC, TACTICS
    from app.domain.services.set_bonus_service import panoplie_type

    build = dict(snap.data) if snap else {}
    if build:
        build["tactic"] = TACTICS.get(build.get("tactic") or DEFAULT_TACTIC, (build.get("tactic"), ""))[0]
        pt = panoplie_type(build.get("panoplie"))
        build["panoplie"] = f"{pt.emoji} {pt.label}"
    return {
        "row": row, "ranks": ranks, "days": days_, "series": series, "band": band,
        "grid": activity.heatmap(e.local for e in evs if e.kind in kinds.ACTIVITY_KINDS),
        "playtime": [per_day.get(d, 0.0) for d in days_],
        "sessions": sorted(sessions, key=lambda s: s.start, reverse=True)[:12],
        "mobs": [(ds.mob_name(c), n) for c, n in mobs.most_common(10)],
        "gold_in": [(kinds.gold_source(s), v) for s, v in gold_in.most_common()],
        "gold_out": [(kinds.gold_source(s), v) for s, v in gold_out.most_common()],
        "timeline": timeline[:60],
        "build": build,
        "snap": snap,
        "players": sorted(((r.pid, r.name) for r in rows), key=lambda x: x[1].lower()),
    }


def describe(ds: Dataset, e: Event) -> tuple[str, str]:
    """(icône, texte) d'un événement pour la chronologie d'un joueur."""
    d = e.data
    if e.kind == kinds.LEVEL_UP:
        return "⬆️", f"Niveau {e.qty}" + (" (admin)" if d.get("src") == "admin" else "")
    if e.kind == kinds.RANK_UP:
        return "🏅", f"Promu rang {e.ref} au niveau {e.qty}"
    if e.kind == kinds.RANK_TRIAL:
        return ("✅" if d.get("passed") else "❌"), f"Épreuve du rang {e.ref} ({d.get('role', '')}) : {e.qty:,}".replace(",", " ")
    if e.kind == kinds.FUSION:
        return "⚒️", f"Fusion {ds.item_name(e.ref)} → {RARITY_LABELS.get(d.get('to', ''), d.get('to', ''))} ({-e.gold:,} or)".replace(",", " ")
    if e.kind == kinds.SHOP_BUY:
        return "🏪", f"Achat {e.qty} × {ds.item_name(e.ref)} ({-e.gold:,} or)".replace(",", " ")
    if e.kind == kinds.TRANSFER:
        return "💸", f"{e.ref.capitalize() if e.ref else 'Virement'} de {e.gold:,} or à {ds.name(d.get('to'))}".replace(",", " ")
    if e.kind == kinds.MARKET_SALE:
        return "🏷️", f"Achat à la brocante : {ds.item_name(e.ref)} ({e.gold:,} or, vendeur {ds.name(d.get('seller'))})".replace(",", " ")
    if e.kind == kinds.RESPEC:
        return "♻️", f"Réinitialisation de l'{e.ref} ({e.qty} points)"
    if e.kind == kinds.TUTORIAL:
        return "🌸", "Tutoriel " + ("terminé" if e.ref == "termine" else "passé")
    if e.kind == kinds.GEAR_DROP:
        return "✨", f"{ds.item_name(e.ref)} {RARITY_LABELS.get(d.get('rarity', ''), '').lower()} trouvée"
    if e.kind == kinds.SEER:
        return "🔮", f"Talent {e.ref} révélé ({e.qty})"
    if e.kind == kinds.OFFERING:
        return "🙏", f"Offrande de {e.gold:,} or".replace(",", " ")
    if e.kind == kinds.BREW:
        return "⚗️", f"{e.qty} × {ds.item_name(e.ref)} préparée(s)"
    if e.kind == kinds.TOWER:
        return ("🗼" if d.get("won") else "💀"), f"Tour : étage {e.qty} " + ("franchi" if d.get("won") else "raté")
    if e.kind == kinds.GOLD:
        return ("🛠️" if e.ref == "admin" else "❔"), f"{'+' if e.gold >= 0 else ''}{e.gold:,} or ({kinds.gold_source(e.ref).label})".replace(",", " ")
    return "•", e.kind


def row_by_pid(ds: Dataset) -> dict[int, PlayerRow]:
    return {r.pid: r for r in build_rows(ds)}
