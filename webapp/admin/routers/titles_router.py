"""Admin : TITRES (titles.json) — liste filtrable, création, édition, suppression.

Découpé de `content_router.py` le 26/10/2026 (roadmap N6). Le bot cache les
titres au démarrage : un changement demande un redémarrage du bot.
"""

from __future__ import annotations


from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse

from webapp.admin import git_sync
from webapp.admin.auth import AdminUser, require_admin
from webapp.admin._shared import get_templates
from webapp.admin.json_writer import append_to_list, load_json as _writer_load
from webapp.admin.routers._content_common import _load_json, _parse_int, _filter_rows, _render, _fmt_title_effects, _delete_from_list

router = APIRouter(prefix="/admin", tags=["admin-titles"])


@router.get("/titles", response_class=HTMLResponse)
async def titles_list(
    request: Request,
    user: AdminUser = Depends(require_admin),
    q: str | None = None,
    condition_type: str | None = None,
):
    data = _load_json("titles.json") or []
    rows = []
    cond_types: set[str] = set()
    for t in data:
        ct = t.get("condition_type", "—")
        cond_types.add(ct)
        effects_str = ", ".join(
            f"{e.get('type')}={e.get('value', '?')}"
            for e in (t.get("effects") or [])
        )
        rows.append({
            "icon": t.get("icon", ""),
            "code": t.get("code", ""),
            "name": t.get("name", ""),
            "condition_type": ct,
            "condition_target": t.get("condition_target", "—") or "—",
            "condition_value": t.get("condition_value", "—"),
            "effects": effects_str or "—",
            "__edit_url__": f"/admin/titles/{t.get('code', '')}/edit",
            "__delete_url__": f"/admin/titles/{t.get('code', '')}/delete",
        })
    filtered = _filter_rows(rows, q, {"condition_type": condition_type})
    return _render(
        request, user,
        title="Titres", icon="🏷️",
        new_url="/admin/titles/new", new_label="Nouveau titre",
        source_label="Définitions : app/infrastructure/content/titles.json — ⚠️ restart bot requis après ajout",
        filter_q=q or "",
        filter_groups=[{
            "name": "condition_type",
            "current": condition_type or "",
            "placeholder": "Tous types de condition",
            "options": [(c, c) for c in sorted(cond_types)],
        }],
        columns=[
            {"label": "Icon", "key": "icon"},
            {"label": "Code", "key": "code"},
            {"label": "Nom", "key": "name"},
            {"label": "Condition", "key": "condition_type"},
            {"label": "Cible", "key": "condition_target"},
            {"label": "Seuil", "key": "condition_value"},
            {"label": "Effets", "key": "effects"},
        ],
        rows=filtered,
    )


@router.get("/titles/new", response_class=HTMLResponse)
async def titles_new_form(request: Request, user: AdminUser = Depends(require_admin)):
    return get_templates().TemplateResponse(
        request, "admin/titles/form.html",
        context={"user": user, "errors": {}, "form_data": {}},
    )


@router.post("/titles")
async def titles_create(request: Request, user: AdminUser = Depends(require_admin)):
    fd = {k: str(v) for k, v in (await request.form()).items()}
    errors = {}
    code = fd.get("code", "").strip()
    name = fd.get("name", "").strip()
    if not code:
        errors["code"] = "Code requis."
    if not name:
        errors["name"] = "Nom requis."
    existing = _writer_load("titles.json", default=[]) or []
    if any(t.get("code") == code for t in existing):
        errors["code"] = f"Code `{code}` existe déjà."
    if errors:
        return get_templates().TemplateResponse(
            request, "admin/titles/form.html",
            context={"user": user, "errors": errors, "form_data": fd},
            status_code=400,
        )
    # effects format : "type:target:value, type::value"
    effects = []
    for chunk in fd.get("effects", "").split(","):
        parts = [p.strip() for p in chunk.split(":")]
        if len(parts) == 3 and parts[0]:
            try:
                value = int(parts[2]) if parts[2] else 0
            except ValueError:
                value = parts[2]
            effects.append({"type": parts[0], "target": parts[1] or None, "value": value})
        elif len(parts) == 2 and parts[0]:
            try:
                value = int(parts[1]) if parts[1] else 0
            except ValueError:
                value = parts[1]
            effects.append({"type": parts[0], "value": value})
    entry = {
        "code": code,
        "name": name,
        "description": fd.get("description", "").strip(),
        "icon": fd.get("icon", "").strip(),
        "exclusive": fd.get("exclusive") == "on",
        "condition_type": fd.get("condition_type", "").strip(),
        "condition_target": fd.get("condition_target", "").strip() or None,
        "condition_value": _parse_int(fd.get("condition_value"), 0),
        "effects": effects,
    }
    append_to_list("titles.json", entry)
    git_sync.push_content(["app/infrastructure/content/titles.json"],
                          f"admin: titre {code} créé")
    return RedirectResponse(f"/admin/titles?q={code}", status_code=303)


@router.get("/titles/{code}/edit", response_class=HTMLResponse)
async def titles_edit_form(
    code: str, request: Request, user: AdminUser = Depends(require_admin),
):
    from webapp.admin.json_writer import find_in_list_by_key
    entry = find_in_list_by_key("titles.json", code)
    if entry is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Titre `{code}` introuvable.")
    fd = {
        "code": entry.get("code", ""),
        "name": entry.get("name", ""),
        "description": entry.get("description", ""),
        "icon": entry.get("icon", ""),
        "exclusive": entry.get("exclusive", False),
        "condition_type": entry.get("condition_type", ""),
        "condition_target": entry.get("condition_target", "") or "",
        "condition_value": entry.get("condition_value", 0),
        "effects": _fmt_title_effects(entry.get("effects")),
    }
    return get_templates().TemplateResponse(
        request, "admin/titles/form.html",
        context={"user": user, "errors": {}, "form_data": fd, "edit_code": code},
    )


@router.post("/titles/{code}")
async def titles_update(
    code: str, request: Request, user: AdminUser = Depends(require_admin),
):
    from webapp.admin.json_writer import find_in_list_by_key, update_in_list_by_key
    if find_in_list_by_key("titles.json", code) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Titre `{code}` introuvable.")
    fd = {k: str(v) for k, v in (await request.form()).items()}
    effects = []
    for chunk in fd.get("effects", "").split(","):
        parts = [p.strip() for p in chunk.split(":")]
        if len(parts) == 3 and parts[0]:
            try:
                value = int(parts[2]) if parts[2] else 0
            except ValueError:
                value = parts[2]
            effects.append({"type": parts[0], "target": parts[1] or None, "value": value})
        elif len(parts) == 2 and parts[0]:
            try:
                value = int(parts[1]) if parts[1] else 0
            except ValueError:
                value = parts[1]
            effects.append({"type": parts[0], "value": value})
    entry = {
        "code": code,
        "name": fd.get("name", "").strip(),
        "description": fd.get("description", "").strip(),
        "icon": fd.get("icon", "").strip(),
        "exclusive": fd.get("exclusive") == "on",
        "condition_type": fd.get("condition_type", "").strip(),
        "condition_target": fd.get("condition_target", "").strip() or None,
        "condition_value": _parse_int(fd.get("condition_value"), 0),
        "effects": effects,
    }
    update_in_list_by_key("titles.json", code, entry)
    git_sync.push_content(["app/infrastructure/content/titles.json"],
                          f"admin: titre {code} modifié")
    return RedirectResponse(f"/admin/titles?q={code}", status_code=303)


@router.post("/titles/{code}/delete")
async def titles_delete(code: str, user: AdminUser = Depends(require_admin)):
    return _delete_from_list("titles.json", code, "Titre", "/admin/titles")
