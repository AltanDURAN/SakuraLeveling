"""Admin : MODÈLES DE QUÊTES quotidiennes et hebdomadaires (daily_quests.json,
weekly_quests.json). Chaque modèle devient une quête concrète par joueur
(quêtes adaptées, 25/10/2026). Découpé de `content_router.py` le 26/10/2026.
"""

from __future__ import annotations


from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse

from webapp.admin.auth import AdminUser, require_admin
from webapp.admin._shared import get_templates
from webapp.admin.json_writer import append_to_list, load_json as _writer_load
from webapp.admin.routers._content_common import _load_json, _parse_int, _parse_reward_items, _filter_rows, _render, _fmt_reward_items, _delete_from_list

router = APIRouter(prefix="/admin", tags=["admin-quests"])


def _quest_entry(fd: dict, code: str, name: str) -> dict:
    """Modèle de quête (quêtes adaptées, 25/10/2026) depuis le formulaire : la
    quête concrète — cible de la zone, quantité au niveau du joueur — est
    tirée pour chaque joueur."""
    try:
        quantity = max(0.1, float(str(fd.get("quantity", "1")).replace(",", ".")))
    except ValueError:
        quantity = 1.0
    roles = [r.strip() for r in fd.get("roles", "").split(",") if r.strip()]
    entry = {
        "code": code,
        "name": name,
        "description": fd.get("description", "").strip(),
        "tier": fd.get("tier", "easy").strip() or "easy",
        "objective_type": fd.get("objective_type", "").strip(),
        "quantity": int(quantity) if quantity.is_integer() else quantity,
        "scale": fd.get("scale", "count").strip() or "count",
        "reward_gold": _parse_int(fd.get("reward_gold"), 0),
        "reward_xp": _parse_int(fd.get("reward_xp"), 0),
        "reward_items": _parse_reward_items(fd.get("reward_items", "")),
    }
    if fd.get("target", "").strip():
        entry["target"] = fd["target"].strip()
    if roles:
        entry["roles"] = roles
    return entry


def _quest_rows(filename: str, scope: str):
    data = _load_json(filename) or []
    rows = []
    for q in data:
        items_str = ", ".join(
            f"{code}×{qty}" for code, qty in (q.get("reward_items") or [])
        ) or "—"
        rows.append({
            "code": q.get("code", ""),
            "name": q.get("name", ""),
            "tier": q.get("tier", "—"),
            "objective_type": q.get("objective_type", "—"),
            "objective_target": q.get("target", q.get("objective_target", "")) or "—",
            "objective_quantity": (f"{q.get('quantity', q.get('objective_quantity', 0)):g} "
                                   f"({q.get('scale', 'count')})"),
            "reward_gold": q.get("reward_gold", 0),
            "reward_xp": q.get("reward_xp", 0),
            "reward_items": items_str,
            "__edit_url__": f"/admin/quests/{scope}/{q.get('code', '')}/edit",
            "__delete_url__": f"/admin/quests/{scope}/{q.get('code', '')}/delete",
        })
    return rows


@router.get("/quests", response_class=HTMLResponse)
async def quests_list(
    request: Request,
    user: AdminUser = Depends(require_admin),
    q: str | None = None,
    tier: str | None = None,
    scope: str = "daily",
):
    filename = "weekly_quests.json" if scope == "weekly" else "daily_quests.json"
    rows = _quest_rows(filename, scope)
    tiers = sorted({r["tier"] for r in rows if r["tier"]})
    filtered = _filter_rows(rows, q, {"tier": tier})
    return _render(
        request, user,
        title=f"Quêtes — {'Hebdomadaires' if scope == 'weekly' else 'Quotidiennes'}",
        icon="📜",
        new_url=f"/admin/quests/new?scope={scope}",
        new_label=f"Nouvelle quête {'hebdo' if scope == 'weekly' else 'quotidienne'}",
        source_label=(
            f"Définitions : app/infrastructure/content/{filename} "
            f"— ⚠️ restart bot requis après ajout."
        ),
        filter_q=q or "",
        filter_groups=[{
            "name": "tier",
            "current": tier or "",
            "placeholder": "Tous les tiers",
            "options": [(t, t) for t in tiers],
        }, {
            "name": "scope",
            "current": scope,
            "placeholder": "Type",
            "options": [("daily", "Quotidiennes"), ("weekly", "Hebdomadaires")],
        }],
        columns=[
            {"label": "Code", "key": "code"},
            {"label": "Nom", "key": "name"},
            {"label": "Tier", "key": "tier"},
            {"label": "Objectif", "key": "objective_type"},
            {"label": "Cible", "key": "objective_target"},
            {"label": "Unités (échelle)", "key": "objective_quantity"},
            {"label": "Or", "key": "reward_gold"},
            {"label": "XP", "key": "reward_xp"},
            {"label": "Items", "key": "reward_items"},
        ],
        rows=filtered,
    )


@router.get("/quests/new", response_class=HTMLResponse)
async def quests_new_form(
    request: Request, user: AdminUser = Depends(require_admin),
    scope: str = "daily",
):
    return get_templates().TemplateResponse(
        request, "admin/quests/form.html",
        context={"user": user, "errors": {}, "form_data": {}, "scope": scope},
    )


@router.post("/quests")
async def quests_create(request: Request, user: AdminUser = Depends(require_admin)):
    fd = {k: str(v) for k, v in (await request.form()).items()}
    scope = fd.get("scope", "daily")
    filename = "weekly_quests.json" if scope == "weekly" else "daily_quests.json"
    errors = {}
    code = fd.get("code", "").strip()
    name = fd.get("name", "").strip()
    if not code:
        errors["code"] = "Code requis."
    if not name:
        errors["name"] = "Nom requis."
    existing = _writer_load(filename, default=[]) or []
    if any(q.get("code") == code for q in existing):
        errors["code"] = f"Code `{code}` existe déjà dans {filename}."
    if errors:
        return get_templates().TemplateResponse(
            request, "admin/quests/form.html",
            context={"user": user, "errors": errors, "form_data": fd, "scope": scope},
            status_code=400,
        )
    entry = _quest_entry(fd, code, name)
    append_to_list(filename, entry)
    return RedirectResponse(f"/admin/quests?q={code}&scope={scope}", status_code=303)


@router.get("/quests/{scope}/{code}/edit", response_class=HTMLResponse)
async def quests_edit_form(
    scope: str, code: str, request: Request,
    user: AdminUser = Depends(require_admin),
):
    from webapp.admin.json_writer import find_in_list_by_key
    filename = "weekly_quests.json" if scope == "weekly" else "daily_quests.json"
    entry = find_in_list_by_key(filename, code)
    if entry is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Quête `{code}` introuvable dans {filename}.")
    fd = {
        "code": entry.get("code", ""),
        "name": entry.get("name", ""),
        "description": entry.get("description", ""),
        "objective_type": entry.get("objective_type", ""),
        "target": entry.get("target", entry.get("objective_target", "")) or "",
        "quantity": entry.get("quantity", entry.get("objective_quantity", 1)),
        "scale": entry.get("scale", "count"),
        "roles": ", ".join(entry.get("roles", []) or []),
        "reward_gold": entry.get("reward_gold", 0),
        "reward_xp": entry.get("reward_xp", 0),
        "reward_items": _fmt_reward_items(entry.get("reward_items")),
        "tier": entry.get("tier", "easy"),
    }
    return get_templates().TemplateResponse(
        request, "admin/quests/form.html",
        context={
            "user": user, "errors": {}, "form_data": fd,
            "scope": scope, "edit_code": code,
        },
    )


@router.post("/quests/{scope}/{code}")
async def quests_update(
    scope: str, code: str, request: Request,
    user: AdminUser = Depends(require_admin),
):
    from webapp.admin.json_writer import find_in_list_by_key, update_in_list_by_key
    filename = "weekly_quests.json" if scope == "weekly" else "daily_quests.json"
    if find_in_list_by_key(filename, code) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Quête `{code}` introuvable.")
    fd = {k: str(v) for k, v in (await request.form()).items()}
    entry = _quest_entry(fd, code, fd.get("name", "").strip())
    update_in_list_by_key(filename, code, entry)
    return RedirectResponse(f"/admin/quests?q={code}&scope={scope}", status_code=303)


@router.post("/quests/{scope}/{code}/delete")
async def quests_delete(scope: str, code: str, user: AdminUser = Depends(require_admin)):
    filename = "weekly_quests.json" if scope == "weekly" else "daily_quests.json"
    return _delete_from_list(filename, code, "Quête", f"/admin/quests?scope={scope}")
