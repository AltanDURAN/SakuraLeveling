"""Admin : SURVEILLANCE du jeu (01/11/2026, demande de l'auteur).

Stats, suivis et alertes pour équilibrer le jeu, voir la méta se construire,
repérer les comportements suspects et savoir combien de temps le contenu va
durer. Données : journal `game_events` + photos quotidiennes (le bot les
écrit), analysées par `app.application.monitoring`.

Toutes les pages partagent le filtre du haut (période, comptes admin) ; le
jeu de données est gardé 90 s entre deux pages (« Actualiser » le relit).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse

from app.application.monitoring import alerting, analysis, dataset
from app.domain.services.gear_service import RARITY_LABELS
from app.domain.services.monitoring import alerts as rules, kinds
from app.domain.services.pacing_service import WEEKDAYS
from app.infrastructure.db.session import get_db_session
from app.infrastructure.monitoring import monitoring_loader
from webapp.admin import charts, json_writer
from webapp.admin._shared import get_templates
from webapp.admin.auth import AdminUser, require_admin

_logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/monitoring", tags=["admin-monitoring"])

PERIODS = ((1, "24 h"), (7, "7 jours"), (30, "30 jours"), (90, "90 jours"))
TABS = (
    ("", "Vue d'ensemble", "🧭"), ("activity", "Activité", "⏱️"), ("economy", "Économie", "💰"),
    ("combat", "Combats", "⚔️"), ("meta", "Méta", "🧩"), ("progression", "Progression", "📈"),
    ("players", "Joueurs", "👥"), ("alerts", "Alertes", "🚨"), ("report", "Rapport", "📰"),
)
#: Flux d'or regroupés en 4 gains et 4 dépenses : 8 couleurs FIXES, chacune
#: à un seul groupe (13 sources pour 8 couleurs, sinon deux sources
#: différentes auraient la même couleur de part et d'autre de zéro).
GAIN_GROUPS = (("Combats", ("combat",), 1), ("Quêtes", ("quete",), 2), ("Daily", ("daily",), 3),
               ("Raid, tour, défis, événements", ("raid", "tour", "defi", "evenement"), 4))
SPEND_GROUPS = (("Sorn (boutique, boosters)", ("boutique", "cartes"), 5), ("Fusion", ("fusion",), 6), ("Potions", ("alchimie",), 7),
                ("Voyante, offrande, taxe, événements", ("voyante", "offrande", "taxe", "evenement"), 8))
GOLD_SLOTS = {code: slot for _, codes, slot in GAIN_GROUPS + SPEND_GROUPS for code in codes}
RARITY_CLASS = {"Commun": "common", "Peu commun": "uncommon", "Rare": "rare", "Épique": "epic",
                "Légendaire": "legendary", "Mythique": "mythic"}


def flow_groups(flows: dict) -> tuple[list[dict], list[dict]]:
    """(gains, dépenses) par jour, regroupés pour le graphique de part et
    d'autre de zéro."""
    n = len(flows["days"])

    def group(spec, source):
        out = []
        for name, codes, slot in spec:
            values = [sum(source.get(c, [0] * n)[i] for c in codes) for i in range(n)]
            out.append({"name": name, "values": values, "slot": slot})
        return out
    return group(GAIN_GROUPS, flows["creation"]), group(SPEND_GROUPS, flows["destruction"])


def _days(raw: str | None) -> int:
    try:
        v = int(raw or 30)
    except ValueError:
        v = 30
    return v if v in {d for d, _ in PERIODS} else 30


def _filters(request: Request) -> dict:
    q = request.query_params
    return {"days": _days(q.get("days")), "admins": q.get("admins") == "1", "fresh": q.get("fresh") == "1"}


def _load(session, f: dict) -> dataset.Dataset:
    return dataset.cached(session, days=f["days"], include_admins=f["admins"], fresh=f["fresh"])


def _alerts(session, fresh: bool = False):
    """Alertes en cours (toujours sur 30 jours, quel que soit le filtre)."""
    ds = dataset.cached(session, days=30, include_admins=False, fresh=fresh)
    if "alerts" not in ds._cache:
        ds._cache["alerts"] = alerting.compute(ds)
    return ds._cache["alerts"]


def _qs(f: dict, **extra) -> str:
    parts = [f"days={f['days']}"]
    if f["admins"]:
        parts.append("admins=1")
    parts += [f"{k}={v}" for k, v in extra.items()]
    return "?" + "&".join(parts)


def _render(request: Request, user: AdminUser, template: str, tab: str, f: dict, ctx: dict, session=None):
    alerts = ctx.pop("_alerts", None)
    if alerts is None and session is not None:
        alerts = _alerts(session)
    counts = {sev: sum(1 for a in alerts or () if a.severity == sev) for sev in rules.SEVERITY_ORDER}
    return get_templates().TemplateResponse(request, f"admin/monitoring/{template}", context={
        "user": user, "tab": tab, "tabs": TABS, "periods": PERIODS, "f": f, "qs": _qs(f),
        "qs_of": lambda **kw: _qs(f, **kw), "viz": charts, "alert_counts": counts,
        "rules": rules, "kinds": kinds, "gold_slots": GOLD_SLOTS, "rarity_class": RARITY_CLASS,
        "weekdays": WEEKDAYS, "now": datetime.now(UTC), "local": dataset.to_local, **ctx})


def _day_labels(days) -> list[str]:
    return [charts.day_label(d) for d in days]


# ================================================================== pages
@router.get("", response_class=HTMLResponse)
async def overview(request: Request, user: AdminUser = Depends(require_admin)):
    f = _filters(request)
    with get_db_session() as session:
        ds = _load(session, f)
        data = analysis.overview(ds)
        alerts = _alerts(session, f["fresh"])
        views = alerting.views(session, alerts)
    gains, spends = flow_groups(data["flows"])
    return _render(request, user, "overview.html", "", f, {
        "d": data, "labels": _day_labels(data["days"]), "_alerts": alerts, "gains": gains, "spends": spends,
        "top_alerts": [v for v in views if not v.muted][:6], "players_total": len(ds.players)})


@router.get("/activity", response_class=HTMLResponse)
async def activity_page(request: Request, user: AdminUser = Depends(require_admin)):
    f = _filters(request)
    with get_db_session() as session:
        ds = _load(session, f)
        data = analysis.activity_page(ds)
        return _render(request, user, "activity.html", "activity", f,
                       {"d": data, "labels": _day_labels(data["days"])}, session)


@router.get("/economy", response_class=HTMLResponse)
async def economy_page(request: Request, user: AdminUser = Depends(require_admin)):
    f = _filters(request)
    with get_db_session() as session:
        ds = _load(session, f)
        data = analysis.economy_page(ds)
        gains, spends = flow_groups(data["flows"])
        return _render(request, user, "economy.html", "economy", f,
                       {"d": data, "labels": _day_labels(data["flows"]["days"]), "gains": gains, "spends": spends},
                       session)


@router.get("/combat", response_class=HTMLResponse)
async def combat_page(request: Request, user: AdminUser = Depends(require_admin)):
    f = _filters(request)
    with get_db_session() as session:
        ds = _load(session, f)
        data = analysis.combat_page(ds)
        return _render(request, user, "combat.html", "combat", f,
                       {"d": data, "labels": _day_labels(data["days"])}, session)


@router.get("/meta", response_class=HTMLResponse)
async def meta_page(request: Request, user: AdminUser = Depends(require_admin)):
    f = _filters(request)
    with get_db_session() as session:
        ds = _load(session, f)
        data = analysis.meta_page(ds, session)
        return _render(request, user, "meta.html", "meta", f, {"d": data}, session)


@router.get("/progression", response_class=HTMLResponse)
async def progression_page(request: Request, user: AdminUser = Depends(require_admin)):
    f = _filters(request)
    with get_db_session() as session:
        ds = _load(session, f)
        data = analysis.progression_page(ds, session)
        return _render(request, user, "progression.html", "progression", f, {"d": data}, session)


@router.get("/players", response_class=HTMLResponse)
async def players_page(request: Request, user: AdminUser = Depends(require_admin)):
    f = _filters(request)
    with get_db_session() as session:
        ds = _load(session, f)
        alerts = _alerts(session)
        flagged: dict[int, list[str]] = {}
        for a in alerts:
            if a.player_id is not None:
                flagged.setdefault(a.player_id, []).append(a.severity)
        data = analysis.players_page(ds, flagged)
        return _render(request, user, "players.html", "players", f, {"d": data, "_alerts": alerts})


@router.get("/players/{player_id}", response_class=HTMLResponse)
async def player_page(player_id: int, request: Request, user: AdminUser = Depends(require_admin)):
    f = _filters(request)
    with get_db_session() as session:
        ds = _load(session, f)
        if player_id not in ds.players:
            ds = dataset.cached(session, days=f["days"], include_admins=True, fresh=f["fresh"])
        data = analysis.player_page(ds, player_id)
        if data is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Joueur #{player_id} introuvable.")
        alerts = _alerts(session)
        mine = [a for a in alerts if a.player_id == player_id]
        return _render(request, user, "player.html", "players", f, {
            "d": data, "labels": _day_labels(data["days"]), "mine": mine, "_alerts": alerts,
            "describe": lambda e: analysis.describe(ds, e),
            "item_name": ds.item_name, "rarity_labels": RARITY_LABELS})


@router.get("/alerts", response_class=HTMLResponse)
async def alerts_page(request: Request, saved: str = "", user: AdminUser = Depends(require_admin)):
    f = _filters(request)
    monitoring_loader.clear_cache()
    with get_db_session() as session:
        alerts = _alerts(session, f["fresh"])
        alerting.sync(session, alerts)       # historique à jour même avant le passage du bot
        views = alerting.views(session, alerts)
        past = alerting.history(session)
        settings = monitoring_loader.get_settings()
        by_cat: dict[str, list] = {}
        for v in views:
            by_cat.setdefault(v.alert.category, []).append(v)
        return _render(request, user, "alerts.html", "alerts", f, {
            "views": views, "by_cat": by_cat, "past": past, "settings": settings, "saved": saved,
            "_alerts": alerts, "thresholds_by_rule": _thresholds_by_rule()})


def _thresholds_by_rule() -> dict[str, list]:
    out: dict[str, list] = {}
    for t in rules.THRESHOLDS:
        out.setdefault(t.rule, []).append(t)
    return out


@router.post("/alerts/settings")
async def save_settings(request: Request, user: AdminUser = Depends(require_admin)):
    form = await request.form()
    current = monitoring_loader.get_settings()
    thresholds = dict(current.thresholds)
    errors = []
    for spec in rules.THRESHOLDS:
        raw = str(form.get(f"t_{spec.key}", "")).strip().replace(",", ".").replace(" ", "")
        if not raw:
            continue
        try:
            value = float(raw)
        except ValueError:
            errors.append(f"« {spec.label} » ({rules.RULES_BY_CODE[spec.rule].label}) doit être un nombre.")
            continue
        if value < 0:
            errors.append(f"« {spec.label} » ne peut pas être négatif.")
            continue
        thresholds[spec.key] = value
    if errors:
        with get_db_session() as session:
            alerts = _alerts(session)
            return _render(request, user, "alerts.html", "alerts", _filters(request), {
                "views": alerting.views(session, alerts), "by_cat": {}, "past": [], "settings": current,
                "saved": "", "errors": errors, "_alerts": alerts, "thresholds_by_rule": _thresholds_by_rule()})
    enabled = {r.code: form.get(f"r_{r.code}") in ("on", "1", "true") for r in rules.RULES}
    severity = str(form.get("notify_min_severity", current.notify_min_severity))
    new = monitoring_loader.MonitoringSettings(
        thresholds=thresholds, rules=enabled, notify=form.get("notify") in ("on", "1", "true"),
        notify_min_severity=severity if severity in rules.SEVERITY_ORDER else current.notify_min_severity)
    json_writer.atomic_write_json("monitoring.json", monitoring_loader.to_json(new))
    monitoring_loader.clear_cache()
    dataset.clear_cache()
    _logger.info("Admin %s a réglé les alertes de surveillance", user.discord_id)
    return RedirectResponse("/admin/monitoring/alerts?saved=1", status_code=303)


@router.post("/alerts/mute")
async def mute_alert(request: Request, user: AdminUser = Depends(require_admin)):
    form = await request.form()
    key = str(form.get("key", ""))[:160]
    try:
        days = float(str(form.get("days", "7")))
    except ValueError:
        days = 7
    with get_db_session() as session:
        if session.get(alerting.MonitoringAlertModel, key) is None:
            alerting.sync(session, _alerts(session))   # pas encore vue par le bot
        alerting.mute(session, key, days)
    back = str(form.get("back", "/admin/monitoring/alerts"))
    return RedirectResponse(back if back.startswith("/admin/monitoring") else "/admin/monitoring/alerts", status_code=303)


@router.get("/report", response_class=HTMLResponse)
async def report_page(request: Request, week: int = 0, user: AdminUser = Depends(require_admin)):
    """Rapport hebdomadaire : la semaine (lundi → dimanche) contre la précédente."""
    from app.application.monitoring import report

    f = _filters(request)
    week = max(0, min(week, 12))
    with get_db_session() as session:
        data = report.weekly(session, weeks_ago=week)
        return _render(request, user, "report.html", "report", f, {"d": data, "week": week}, session)


@router.get("/refresh")
async def refresh(request: Request, back: str = "/admin/monitoring", user: AdminUser = Depends(require_admin)):
    dataset.clear_cache()
    return RedirectResponse(back if back.startswith("/admin/monitoring") else "/admin/monitoring", status_code=303)

