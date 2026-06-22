"""Routes admin pour gérer les mobs (CRUD, V1 sans delete)."""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi import HTTPException

from app.infrastructure.db.repositories.item_repository import ItemRepository
from app.infrastructure.db.repositories.mob_repository import MobRepository
from app.infrastructure.db.session import get_db_session
from webapp.admin import content_sync, git_sync
from webapp.admin.auth import AdminUser, require_admin
from webapp.admin._shared import get_templates


_logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/mobs", tags=["admin-mobs"])




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


def _clamp_mob_stats(
    *, max_hp: int, attack: int, defense: int, speed: int,
    crit_chance: int, crit_damage: int, dodge: int, hp_regeneration: int,
    xp_reward: int, gold_reward: int, spawn_weight: int,
    current_hp: int | None = None,
) -> dict:
    """Borne les stats aux conventions de combat V2 (crit_chance/dodge 0..100,
    crit_damage ≥ 0 avec 100=neutre, current_hp ≤ max_hp). Clampage silencieux
    pour que l'admin puisse itérer sans avoir à corriger lui-même les overflows."""
    mh = max(1, max_hp)
    out = {
        "max_hp": mh,
        "attack": max(0, attack),
        "defense": max(0, defense),
        "speed": max(0, speed),
        "crit_chance": max(0, min(crit_chance, 100)),
        "crit_damage": max(0, crit_damage),
        "dodge": max(0, min(dodge, 100)),
        "hp_regeneration": max(0, hp_regeneration),
        "xp_reward": max(0, xp_reward),
        "gold_reward": max(0, gold_reward),
        "spawn_weight": max(1, spawn_weight),
    }
    if current_hp is not None:
        out["current_hp"] = max(0, min(current_hp, mh))
    return out


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
    with get_db_session() as session:
        item_codes = [it.code for it in ItemRepository(session).list_all()]
    return get_templates().TemplateResponse(
        request, "admin/mobs/form.html",
        context={"user": user, "mob": None, "errors": {},
                 "loot_table_json": "[]", "item_codes": item_codes},
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

        stats = _clamp_mob_stats(
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
            spawn_weight=_parse_int(form_data.get("spawn_weight"), 1),
        )
        repo.create(
            code=code,
            name=name,
            description=form_data.get("description", "").strip(),
            image_name=form_data.get("image_name", "").strip(),
            family=form_data.get("family", "").strip() or "unknown",
            element=form_data.get("element", "").strip(),
            loot_table=_parse_loot_table(form_data.get("loot_table")),
            **stats,
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
        item_codes = [it.code for it in ItemRepository(session).list_all()]
    return get_templates().TemplateResponse(
        request, "admin/mobs/form.html",
        context={
            "user": user, "mob": mob,
            # JSON compact pour initialiser l'éditeur Alpine (champ caché).
            "loot_table_json": json.dumps(mob.loot_table or [], ensure_ascii=False),
            "item_codes": item_codes,
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
        stats = _clamp_mob_stats(
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
            spawn_weight=_parse_int(form_data.get("spawn_weight"), existing.spawn_weight),
        )
        repo.update_by_code(
            code=code,
            name=form_data.get("name", existing.name),
            description=form_data.get("description", existing.description),
            image_name=form_data.get("image_name", existing.image_name).strip() or existing.image_name,
            family=form_data.get("family", existing.family or "").strip() or existing.family,
            element=form_data.get("element", existing.element or "").strip(),
            loot_table=_parse_loot_table(form_data.get("loot_table")),
            **stats,
        )
    return RedirectResponse(f"/admin/mobs?q={code}", status_code=303)


@router.post("/{code}/delete")
async def mobs_delete(code: str, user: AdminUser = Depends(require_admin)):
    """Suppression en cascade : retire le mob de la DB (+ compteurs de kills)
    et de mobs.json."""
    from app.application.use_cases.delete_mob import DeleteMobUseCase
    with get_db_session() as session:
        result = DeleteMobUseCase().execute(session, code)
    if not result.deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Mob `{code}` introuvable.")
    touched = content_sync.delete_mob_json(code)
    _logger.info("Admin %s a supprimé le mob %s (kills retirés: %s, json: %s)",
                 user.discord_id, code, result.kills_removed, touched)
    if touched:
        git_sync.push_content([f"app/infrastructure/content/{f}" for f in touched],
                              f"admin: mob {code} supprimé (cascade)")
    return RedirectResponse("/admin/mobs", status_code=303)
