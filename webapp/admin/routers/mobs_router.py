"""Routes admin pour gérer les mobs (CRUD, V1 sans delete)."""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi import HTTPException

from app.infrastructure.db.repositories.mob_repository import MobRepository
from app.infrastructure.db.session import get_db_session
from webapp.admin.auth import AdminUser, require_admin


_logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/mobs", tags=["admin-mobs"])


def get_templates():
    from webapp.main import templates
    return templates


def _parse_optional_int(raw: str | None) -> int | None:
    if raw is None:
        return None
    raw = raw.strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _parse_int(raw: str | None, default: int = 0) -> int:
    v = _parse_optional_int(raw)
    return v if v is not None else default


def _parse_loot_table(raw: str | None) -> list[dict] | None:
    """Le form envoie un textarea JSON. Liste vide → None."""
    if raw is None:
        return None
    raw = raw.strip()
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return parsed
        return None
    except json.JSONDecodeError:
        return None


@router.get("", response_class=HTMLResponse)
async def mobs_list(
    request: Request,
    user: AdminUser = Depends(require_admin),
    family: str | None = None,
    q: str | None = None,
):
    with get_db_session() as session:
        mobs = MobRepository(session).list_all()

    if family:
        mobs = [m for m in mobs if (m.family or "") == family]
    if q:
        q_lower = q.lower()
        mobs = [
            m for m in mobs
            if q_lower in m.code.lower() or q_lower in m.name.lower()
        ]

    mobs.sort(key=lambda m: (m.family or "zzz", m.code))

    return get_templates().TemplateResponse(
        request, "admin/mobs/list.html",
        context={
            "user": user, "mobs": mobs,
            "filter_family": family or "",
            "filter_q": q or "",
            "all_families": sorted({m.family for m in mobs if m.family}),
        },
    )


@router.get("/new", response_class=HTMLResponse)
async def mobs_new_form(
    request: Request,
    user: AdminUser = Depends(require_admin),
):
    return get_templates().TemplateResponse(
        request, "admin/mobs/form.html",
        context={"user": user, "mob": None, "errors": {}},
    )


@router.post("")
async def mobs_create(
    request: Request,
    user: AdminUser = Depends(require_admin),
):
    form = await request.form()
    form_data = {k: str(v) for k, v in form.items()}
    errors: dict[str, str] = {}

    code = form_data.get("code", "").strip()
    name = form_data.get("name", "").strip()
    if not code:
        errors["code"] = "Code requis."
    if not name:
        errors["name"] = "Nom requis."

    max_hp = _parse_int(form_data.get("max_hp"), 1)
    if max_hp < 1:
        errors["max_hp"] = "PV max doit être ≥ 1."

    if errors:
        return get_templates().TemplateResponse(
            request, "admin/mobs/form.html",
            context={
                "user": user, "mob": None,
                "form_data": form_data, "errors": errors,
            },
            status_code=400,
        )

    with get_db_session() as session:
        repo = MobRepository(session)
        if repo.get_by_code(code) is not None:
            errors["code"] = f"Le code `{code}` existe déjà."
            return get_templates().TemplateResponse(
                request, "admin/mobs/form.html",
                context={
                    "user": user, "mob": None,
                    "form_data": form_data, "errors": errors,
                },
                status_code=400,
            )

        repo.create(
            code=code,
            name=name,
            description=form_data.get("description", "").strip(),
            max_hp=max_hp,
            attack=_parse_int(form_data.get("attack"), 1),
            defense=_parse_int(form_data.get("defense"), 0),
            speed=_parse_int(form_data.get("speed"), 1),
            crit_chance=_parse_int(form_data.get("crit_chance"), 0),
            crit_damage=_parse_int(form_data.get("crit_damage"), 100),
            dodge=_parse_int(form_data.get("dodge"), 0),
            hp_regeneration=_parse_int(form_data.get("hp_regeneration"), 0),
            xp_reward=_parse_int(form_data.get("xp_reward"), 0),
            gold_reward=_parse_int(form_data.get("gold_reward"), 0),
            image_name=form_data.get("image_name", "").strip(),
            family=form_data.get("family", "").strip() or "unknown",
            spawn_weight=_parse_int(form_data.get("spawn_weight"), 1),
            loot_table=_parse_loot_table(form_data.get("loot_table")),
        )

    return RedirectResponse(f"/admin/mobs?q={code}", status_code=303)


@router.get("/{code}/edit", response_class=HTMLResponse)
async def mobs_edit_form(
    code: str, request: Request,
    user: AdminUser = Depends(require_admin),
):
    with get_db_session() as session:
        mob = MobRepository(session).get_by_code(code)
    if mob is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Mob `{code}` introuvable.")
    return get_templates().TemplateResponse(
        request, "admin/mobs/form.html",
        context={
            "user": user, "mob": mob,
            "loot_table_json": json.dumps(mob.loot_table or [], ensure_ascii=False, indent=2),
            "errors": {},
        },
    )


@router.post("/{code}")
async def mobs_update(
    code: str, request: Request,
    user: AdminUser = Depends(require_admin),
):
    form = await request.form()
    form_data = {k: str(v) for k, v in form.items()}

    with get_db_session() as session:
        repo = MobRepository(session)
        existing = repo.get_by_code(code)
        if existing is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, f"Mob `{code}` introuvable.",
            )
        repo.update_by_code(
            code=code,
            name=form_data.get("name", existing.name),
            description=form_data.get("description", existing.description),
            max_hp=_parse_int(form_data.get("max_hp"), existing.max_hp),
            current_hp=_parse_int(form_data.get("current_hp"), existing.current_hp),
            attack=_parse_int(form_data.get("attack"), existing.attack),
            defense=_parse_int(form_data.get("defense"), existing.defense),
            speed=_parse_int(form_data.get("speed"), existing.speed),
            crit_chance=_parse_int(form_data.get("crit_chance"), existing.crit_chance),
            crit_damage=_parse_int(form_data.get("crit_damage"), existing.crit_damage),
            dodge=_parse_int(form_data.get("dodge"), existing.dodge),
            hp_regeneration=_parse_int(form_data.get("hp_regeneration"), existing.hp_regeneration),
            xp_reward=_parse_int(form_data.get("xp_reward"), existing.xp_reward),
            gold_reward=_parse_int(form_data.get("gold_reward"), existing.gold_reward),
            image_name=form_data.get("image_name", existing.image_name).strip() or existing.image_name,
            family=form_data.get("family", existing.family or "").strip() or existing.family,
            spawn_weight=_parse_int(form_data.get("spawn_weight"), existing.spawn_weight),
            loot_table=_parse_loot_table(form_data.get("loot_table")),
        )
    return RedirectResponse(f"/admin/mobs?q={code}", status_code=303)
