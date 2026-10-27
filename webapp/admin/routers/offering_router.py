"""Admin : OFFRANDE COMMUNE (offering.json + jauge en base).

Demande de l'auteur (27/10/2026) : régler depuis le site la formule du prix,
la durée de la bénédiction et les divinités, et corriger le prix de la jauge
en cours. Le bot relit `offering.json` dès qu'il change (cache par date de
modification) : pas de redémarrage.
"""

from __future__ import annotations

import logging
import re
import unicodedata

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse

from app.domain.services import offering_service as osvc
from app.infrastructure.db.models.offering_model import OfferingStateModel
from app.infrastructure.db.session import get_db_session
from app.infrastructure.offering import offering_loader
from webapp.admin import json_writer
from webapp.admin._shared import get_templates
from webapp.admin.auth import AdminUser, require_admin

_logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/offering", tags=["admin-offering"])

_FILE = "offering.json"
_PREVIEW_DAYS = (7, 30, 60, 90, 180)


def _data() -> dict:
    data = json_writer.load_json(_FILE, {}) or {}
    data.setdefault("params", {})
    data.setdefault("deities", [])
    return data


def _save(data: dict) -> None:
    json_writer.atomic_write_json(_FILE, data)
    offering_loader.clear_cache()


def _slug(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def _num(form, key: str, cast=float):
    try:
        return cast(str(form.get(key, "")).replace(",", ".").replace(" ", ""))
    except (TypeError, ValueError):
        return None


def _gauge() -> dict | None:
    with get_db_session() as session:
        row = session.get(OfferingStateModel, 1)
        if row is None:
            return None
        deity = offering_loader.get_deity(row.deity_code)
        return {"cycle": row.cycle, "target": row.target, "contributed": row.contributed,
                "fills": row.fills, "filled_on": row.filled_on, "deity": deity,
                "blessing_until": row.blessing_until}


def _render(request: Request, user: AdminUser, *, errors: list[str] | None = None,
            saved: str = "", code: int = 200):
    params = offering_loader.get_params()
    preview = {day: (target, total) for day, target, total in osvc.simulate_daily(params, max(_PREVIEW_DAYS))
               if day in _PREVIEW_DAYS}
    return get_templates().TemplateResponse(
        request, "admin/offering.html", status_code=code,
        context={"user": user, "params": params, "deities": offering_loader.list_deities(),
                 "effects": osvc.EFFECT_LABELS, "gauge": _gauge(), "preview": preview,
                 "preview_days": _PREVIEW_DAYS, "errors": errors or [], "saved": saved},
    )


@router.get("", response_class=HTMLResponse)
async def offering_page(request: Request, saved: str = "", user: AdminUser = Depends(require_admin)):
    offering_loader.clear_cache()
    return _render(request, user, saved=saved)


@router.post("/params")
async def save_params(request: Request, user: AdminUser = Depends(require_admin)):
    form = await request.form()
    values = {
        "base_target": _num(form, "base_target", int), "step_per_fill": _num(form, "step_per_fill", int),
        "growth_pct": _num(form, "growth_pct"), "decay_pct": _num(form, "decay_pct"),
        "blessing_hours": _num(form, "blessing_hours", int),
    }
    if any(v is None for v in values.values()):
        return _render(request, user, errors=["Tous les champs de la formule sont des nombres."], code=400)
    params = osvc.OfferingParams(**values)
    errors = osvc.validate_params(params)
    if errors:
        return _render(request, user, errors=errors, code=400)
    data = _data()
    data["params"] = values
    _save(data)
    _logger.info("Admin %s a réglé l'offrande : %s", user.discord_id, values)
    return RedirectResponse("/admin/offering?saved=params", status_code=303)


@router.post("/gauge")
async def save_gauge(request: Request, user: AdminUser = Depends(require_admin)):
    """Corrige le prix de la jauge EN COURS (la formule s'applique ensuite)."""
    form = await request.form()
    target = _num(form, "target", int)
    if target is None or target < 1:
        return _render(request, user, errors=["Le prix de la jauge en cours doit être d'au moins 1 or."], code=400)
    from app.application.use_cases.offering import _state

    with get_db_session(atomic=True) as session:
        _state(session).target = target
    _logger.info("Admin %s a fixé la jauge en cours à %s or", user.discord_id, target)
    return RedirectResponse("/admin/offering?saved=gauge", status_code=303)


def _deity_from(form, code: str) -> tuple[dict | None, list[str]]:
    errors = []
    name = str(form.get("name", "")).strip()
    effect = str(form.get("effect", "")).strip()
    value = _num(form, "value")
    if not name:
        errors.append("Une divinité a besoin d'un nom.")
    if effect not in osvc.EFFECTS:
        errors.append(f"Effet inconnu : « {effect} ».")
    if value is None or value < 0:
        errors.append("L'ampleur de l'effet est un nombre positif.")
    if errors:
        return None, errors
    entry = {
        "code": code, "name": name, "title": str(form.get("title", "")).strip(),
        "emoji": str(form.get("emoji", "")).strip() or "✨", "effect": effect,
        "value": int(value) if float(value).is_integer() else value,
        # « X » isolé = l'ampleur (pas celui de « XP »).
        "blessing": str(form.get("blessing", "")).strip() or re.sub(r"\bX\b", f"{value:g}", osvc.EFFECT_LABELS[effect]),
    }
    return entry, []


@router.post("/deities")
async def add_deity(request: Request, user: AdminUser = Depends(require_admin)):
    form = await request.form()
    data = _data()
    code = _slug(str(form.get("code", "")).strip() or str(form.get("name", "")))
    if not code:
        return _render(request, user, errors=["Une divinité a besoin d'un nom."], code=400)
    if any(d.get("code") == code for d in data["deities"]):
        return _render(request, user, errors=[f"Le code « {code} » existe déjà."], code=400)
    entry, errors = _deity_from(form, code)
    if errors:
        return _render(request, user, errors=errors, code=400)
    data["deities"].append(entry)
    _save(data)
    _logger.info("Admin %s a ajouté la divinité %s", user.discord_id, code)
    return RedirectResponse("/admin/offering?saved=deity", status_code=303)


@router.post("/deities/{code}")
async def edit_deity(code: str, request: Request, user: AdminUser = Depends(require_admin)):
    form = await request.form()
    data = _data()
    index = next((i for i, d in enumerate(data["deities"]) if d.get("code") == code), None)
    if index is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Divinité `{code}` introuvable.")
    entry, errors = _deity_from(form, code)
    if errors:
        return _render(request, user, errors=errors, code=400)
    data["deities"][index] = entry
    _save(data)
    _logger.info("Admin %s a modifié la divinité %s", user.discord_id, code)
    return RedirectResponse("/admin/offering?saved=deity", status_code=303)


@router.post("/deities/{code}/delete")
async def delete_deity(code: str, request: Request, user: AdminUser = Depends(require_admin)):
    data = _data()
    remaining = [d for d in data["deities"] if d.get("code") != code]
    if len(remaining) == len(data["deities"]):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Divinité `{code}` introuvable.")
    if len(remaining) < 2:
        return _render(request, user, errors=["Il faut garder au moins deux divinités (jamais deux fois la même de suite)."],
                       code=400)
    data["deities"] = remaining
    _save(data)
    _logger.info("Admin %s a retiré la divinité %s", user.discord_id, code)
    return RedirectResponse("/admin/offering?saved=deity", status_code=303)
