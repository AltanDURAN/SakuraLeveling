"""Admin : RYTHME DU JEU (pacing.json).

Demande de l'auteur (27/10/2026) : régler depuis le site le délai entre deux
monstres dans les zones — et ce qui va avec : délai après une fuite, temps
pour rejoindre, heures calmes, meutes, pause ou délai propre à une zone, et
le rendez-vous du raid. Le bot relit `pacing.json` dès qu'il change (cache
par date de modification) : pas de redémarrage.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse

from app.domain.services import pacing_service as psvc
from app.infrastructure.encounters.farm_zone_loader import list_zones
from app.infrastructure.pacing import pacing_loader
from webapp.admin import json_writer
from webapp.admin._shared import get_templates
from webapp.admin.auth import AdminUser, require_admin

_logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/pacing", tags=["admin-pacing"])

_FILE = "pacing.json"


def _data() -> dict:
    data = json_writer.load_json(_FILE, {}) or {}
    data.setdefault("zones", {})
    data.setdefault("zone_overrides", {})
    data.setdefault("raid", {})
    return data


def _num(form, key: str, cast=float):
    try:
        return cast(str(form.get(key, "")).replace(",", ".").replace(" ", ""))
    except (TypeError, ValueError):
        return None


def _render(request: Request, user: AdminUser, *, errors: list[str] | None = None,
            saved: str = "", code: int = 200):
    pacing = pacing_loader.get_pacing()
    zones = [{**z, "override": pacing.override(z["channel_id"])} for z in list_zones() if z["channel_id"]]
    return get_templates().TemplateResponse(
        request, "admin/pacing.html", status_code=code,
        context={"user": user, "pacing": pacing, "zones": zones, "weekdays": psvc.WEEKDAYS,
                 "fight_label": psvc.fight_label(pacing.raid), "close_label": psvc.close_label(pacing.raid),
                 "errors": errors or [], "saved": saved},
    )


def _save(request: Request, user: AdminUser, data: dict, saved: str, what: str):
    """Valide le réglage complet puis l'écrit (rien n'est écrit s'il est invalide)."""
    errors = psvc.validate(pacing_loader.parse(data))
    if errors:
        return _render(request, user, errors=errors, code=400)
    json_writer.atomic_write_json(_FILE, data)
    pacing_loader.clear_cache()
    _logger.info("Admin %s a réglé le rythme (%s)", user.discord_id, what)
    return RedirectResponse(f"/admin/pacing?saved={saved}", status_code=303)


@router.get("", response_class=HTMLResponse)
async def pacing_page(request: Request, saved: str = "", user: AdminUser = Depends(require_admin)):
    pacing_loader.clear_cache()
    return _render(request, user, saved=saved)


@router.post("/zones")
async def save_zones(request: Request, user: AdminUser = Depends(require_admin)):
    form = await request.form()
    values = {
        "respawn_min_minutes": _num(form, "respawn_min_minutes"),
        "respawn_max_minutes": _num(form, "respawn_max_minutes"),
        "flee_respawn_minutes": _num(form, "flee_respawn_minutes"),
        "join_window_minutes": _num(form, "join_window_minutes"),
        "quiet_start_hour": _num(form, "quiet_start_hour", int),
        "quiet_end_hour": _num(form, "quiet_end_hour", int),
        "pack_chance_pct": _num(form, "pack_chance_pct"),
        "pack_of_three_pct": _num(form, "pack_of_three_pct"),
    }
    if any(v is None for v in values.values()):
        return _render(request, user, errors=["Tous les champs des zones sont des nombres."], code=400)
    data = _data()
    data["zones"] = values
    return _save(request, user, data, "zones", f"zones {values}")


@router.post("/zones/{channel_id}")
async def save_zone_override(channel_id: int, request: Request, user: AdminUser = Depends(require_admin)):
    if channel_id not in {z["channel_id"] for z in list_zones()}:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Zone `{channel_id}` introuvable.")
    form = await request.form()
    low_raw, high_raw = str(form.get("respawn_min_minutes", "")).strip(), str(form.get("respawn_max_minutes", "")).strip()
    low = _num(form, "respawn_min_minutes") if low_raw else None
    high = _num(form, "respawn_max_minutes") if high_raw else None
    if (low_raw and low is None) or (high_raw and high is None):
        return _render(request, user, errors=["Le délai d'une zone est un nombre de minutes (ou vide)."], code=400)
    if high is not None and low is None:
        return _render(request, user, errors=["Indique au moins le délai minimum de la zone."], code=400)
    entry = {"paused": form.get("paused") in ("on", "1", "true"),
             "respawn_min_minutes": low, "respawn_max_minutes": high}
    data = _data()
    if entry == {"paused": False, "respawn_min_minutes": None, "respawn_max_minutes": None}:
        data["zone_overrides"].pop(str(channel_id), None)      # comme les autres zones
    else:
        data["zone_overrides"][str(channel_id)] = entry
    return _save(request, user, data, "zone", f"zone {channel_id} {entry}")


@router.post("/raid")
async def save_raid(request: Request, user: AdminUser = Depends(require_admin)):
    form = await request.form()
    fight = str(form.get("fight_time", "")).strip()
    try:
        fight_hour, fight_minute = (int(x) for x in fight.split(":", 1))
    except ValueError:
        return _render(request, user, errors=["L'heure de l'assaut s'écrit HH:MM."], code=400)
    values = {
        "spawn_weekday": _num(form, "spawn_weekday", int),
        "spawn_hour": _num(form, "spawn_hour", int),
        "fight_hour": fight_hour,
        "fight_minute": fight_minute,
        "registration_close_minutes": _num(form, "registration_close_minutes", int),
    }
    if any(v is None for v in values.values()):
        return _render(request, user, errors=["Tous les champs du raid sont des nombres."], code=400)
    data = _data()
    data["raid"] = values
    return _save(request, user, data, "raid", f"raid {values}")
