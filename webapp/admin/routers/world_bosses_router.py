"""Admin : WORLD BOSS (boss_definitions.json) — liste, création, édition,
suppression. Les capacités se recalculent avec `scripts/restat_bosses.py`.
Découpé de `content_router.py` le 26/10/2026 (roadmap N6).
"""

from __future__ import annotations


from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse

from webapp.admin.auth import AdminUser, require_admin
from webapp.admin._shared import get_templates
from webapp.admin.json_writer import append_to_list, load_json as _writer_load
from webapp.admin.routers._content_common import _load_json, _parse_int, _parse_kv_pairs, _filter_rows, _render, _fmt_kv_pairs, _delete_from_list

router = APIRouter(prefix="/admin", tags=["admin-world-bosses"])


@router.get("/world-bosses", response_class=HTMLResponse)
async def world_bosses_list(
    request: Request,
    user: AdminUser = Depends(require_admin),
    q: str | None = None,
    tier: str | None = None,
):
    data = _load_json("boss_definitions.json") or []
    rows = []
    tiers: set[str] = set()
    for b in data:
        if b.get("tier"):
            tiers.add(b["tier"])
        mods = b.get("modifiers") or {}
        mods_str = ", ".join(f"{k}={v}" for k, v in mods.items()) or "—"
        rows.append({
            "code": b.get("code", ""),
            "name": b.get("name", ""),
            "tier": b.get("tier", "—"),
            "max_hp": b.get("max_hp", 0),
            "attack": b.get("attack", 0),
            "defense": b.get("defense", 0),
            "speed": b.get("speed", 0),
            "spawn_weight": b.get("spawn_weight", 0),
            "modifiers": mods_str,
            "__edit_url__": f"/admin/world-bosses/{b.get('code', '')}/edit",
            "__delete_url__": f"/admin/world-bosses/{b.get('code', '')}/delete",
        })
    filtered = _filter_rows(rows, q, {"tier": tier})
    return _render(
        request, user,
        title="World Bosses", icon="🐉",
        new_url="/admin/world-bosses/new", new_label="Nouveau boss",
        source_label="Définitions : app/infrastructure/content/boss_definitions.json — ⚠️ restart bot requis",
        filter_q=q or "",
        filter_groups=[{
            "name": "tier",
            "current": tier or "",
            "placeholder": "Tous les tiers",
            "options": [(t, t) for t in sorted(tiers)],
        }],
        columns=[
            {"label": "Code", "key": "code"},
            {"label": "Nom", "key": "name"},
            {"label": "Tier", "key": "tier"},
            {"label": "PV", "key": "max_hp"},
            {"label": "Atk", "key": "attack"},
            {"label": "Def", "key": "defense"},
            {"label": "Vit", "key": "speed"},
            {"label": "Poids", "key": "spawn_weight"},
            {"label": "Modifiers", "key": "modifiers"},
        ],
        rows=filtered,
    )


@router.get("/world-bosses/new", response_class=HTMLResponse)
async def bosses_new_form(request: Request, user: AdminUser = Depends(require_admin)):
    return get_templates().TemplateResponse(
        request, "admin/world_bosses/form.html",
        context={"user": user, "errors": {}, "form_data": {}},
    )


@router.post("/world-bosses")
async def bosses_create(request: Request, user: AdminUser = Depends(require_admin)):
    fd = {k: str(v) for k, v in (await request.form()).items()}
    errors = {}
    code = fd.get("code", "").strip()
    name = fd.get("name", "").strip()
    if not code:
        errors["code"] = "Code requis."
    if not name:
        errors["name"] = "Nom requis."
    existing = _writer_load("boss_definitions.json", default=[]) or []
    if any(b.get("code") == code for b in existing):
        errors["code"] = f"Code `{code}` existe déjà."
    if errors:
        return get_templates().TemplateResponse(
            request, "admin/world_bosses/form.html",
            context={"user": user, "errors": errors, "form_data": fd},
            status_code=400,
        )
    # modifiers format : "damage_immunity_threshold=5, enrage_below_pct=20"
    modifiers = _parse_kv_pairs(fd.get("modifiers", ""))
    entry = {
        "code": code,
        "name": name,
        "description": fd.get("description", "").strip(),
        "image_name": fd.get("image_name", "").strip(),
        "tier": fd.get("tier", "intro").strip() or "intro",
        "spawn_weight": _parse_int(fd.get("spawn_weight"), 100),
        "max_hp": _parse_int(fd.get("max_hp"), 10000),
        "attack": _parse_int(fd.get("attack"), 50),
        "defense": _parse_int(fd.get("defense"), 20),
        "speed": _parse_int(fd.get("speed"), 5),
        "crit_chance": _parse_int(fd.get("crit_chance"), 0),
        "crit_damage": _parse_int(fd.get("crit_damage"), 100),
        "dodge": _parse_int(fd.get("dodge"), 0),
        "modifiers": modifiers,
        "lore": fd.get("lore", "").strip(),
    }
    append_to_list("boss_definitions.json", entry)
    return RedirectResponse(f"/admin/world-bosses?q={code}", status_code=303)


def _scalar_modifiers(modifiers: dict | None) -> dict:
    """Les modifiers éditables en `clé=valeur` (un booléen devient 1 / 0) ;
    les invocations (dict) restent dans le JSON, conservées à l'édition."""
    return {k: int(v) if isinstance(v, bool) else v for k, v in (modifiers or {}).items()
            if not isinstance(v, (dict, list))}


@router.get("/world-bosses/{code}/edit", response_class=HTMLResponse)
async def bosses_edit_form(
    code: str, request: Request, user: AdminUser = Depends(require_admin),
):
    from webapp.admin.json_writer import find_in_list_by_key
    entry = find_in_list_by_key("boss_definitions.json", code)
    if entry is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Boss `{code}` introuvable.")
    fd = {
        "code": entry.get("code", ""),
        "name": entry.get("name", ""),
        "description": entry.get("description", ""),
        "image_name": entry.get("image_name", ""),
        "tier": entry.get("tier", ""),
        "spawn_weight": entry.get("spawn_weight", 100),
        "max_hp": entry.get("max_hp", 10000),
        "attack": entry.get("attack", 50),
        "defense": entry.get("defense", 20),
        "speed": entry.get("speed", 5),
        "crit_chance": entry.get("crit_chance", 0),
        "crit_damage": entry.get("crit_damage", 100),
        "dodge": entry.get("dodge", 0),
        "modifiers": _fmt_kv_pairs(_scalar_modifiers(entry.get("modifiers"))),
        "lore": entry.get("lore", ""),
    }
    return get_templates().TemplateResponse(
        request, "admin/world_bosses/form.html",
        context={"user": user, "errors": {}, "form_data": fd, "edit_code": code},
    )


@router.post("/world-bosses/{code}")
async def bosses_update(
    code: str, request: Request, user: AdminUser = Depends(require_admin),
):
    from webapp.admin.json_writer import find_in_list_by_key, update_in_list_by_key
    existing = find_in_list_by_key("boss_definitions.json", code)
    if existing is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Boss `{code}` introuvable.")
    fd = {k: str(v) for k, v in (await request.form()).items()}
    # Ce que le formulaire ne montre pas (élément, butin, phases, ultime,
    # gardes, invocations…) est conservé : avant, éditer un boss l'effaçait.
    nested = {k: v for k, v in (existing.get("modifiers") or {}).items() if isinstance(v, (dict, list))}
    entry = {
        **existing,
        "code": code,
        "name": fd.get("name", "").strip(),
        "description": fd.get("description", "").strip(),
        "image_name": fd.get("image_name", "").strip(),
        "tier": fd.get("tier", "intro").strip() or "intro",
        "spawn_weight": _parse_int(fd.get("spawn_weight"), 100),
        "max_hp": _parse_int(fd.get("max_hp"), 10000),
        "attack": _parse_int(fd.get("attack"), 50),
        "defense": _parse_int(fd.get("defense"), 20),
        "speed": _parse_int(fd.get("speed"), 5),
        "crit_chance": _parse_int(fd.get("crit_chance"), 0),
        "crit_damage": _parse_int(fd.get("crit_damage"), 100),
        "dodge": _parse_int(fd.get("dodge"), 0),
        "modifiers": {**nested, **_parse_kv_pairs(fd.get("modifiers", ""))},
        "lore": fd.get("lore", "").strip(),
    }
    update_in_list_by_key("boss_definitions.json", code, entry)
    return RedirectResponse(f"/admin/world-bosses?q={code}", status_code=303)


@router.post("/world-bosses/{code}/delete")
async def bosses_delete(code: str, user: AdminUser = Depends(require_admin)):
    return _delete_from_list("boss_definitions.json", code, "Boss", "/admin/world-bosses")
