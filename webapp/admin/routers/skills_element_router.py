"""Routes admin CRUD des compétences élémentaires (element_skills.json).

24 compétences (8 éléments × 3 rôles), code = '<element>_<role>'. Chaque skill
a un effet basique (chaque tour) et une spéciale (proc %). Effets en % de stats
avec un coût en mana. Reseed-safe + git via content_sync/atomic_write_json."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse

from app.infrastructure.elements import element_skill_loader
from webapp.admin import content_sync
from webapp.admin.auth import AdminUser, require_admin
from webapp.admin._shared import get_templates

_logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/competences", tags=["admin-competences"])

ELEMENTS = ["eau", "feu", "plante", "glace", "vent", "terre", "tenebre", "lumiere"]
ROLES = ["offensive", "defensive", "support"]
KINDS = ["damage", "shield_self", "heal_ally", "shield_team"]


def _parse_float(raw, default=0.0) -> float:
    try:
        return float(str(raw).strip().replace(",", "."))
    except (TypeError, ValueError):
        return default


def _parse_int(raw, default=0) -> int:
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return default


def _skills_sorted() -> list:
    element_skill_loader.clear_cache()
    skills = list(element_skill_loader.all_skills().values())
    order = {e: i for i, e in enumerate(ELEMENTS)}
    role_order = {r: i for i, r in enumerate(ROLES)}
    return sorted(skills, key=lambda s: (order.get(s.element, 99), role_order.get(s.role, 99)))


@router.get("")
async def competences_list(request: Request, user: AdminUser = Depends(require_admin)):
    return get_templates().TemplateResponse(
        request, "admin/competences/list.html",
        context={"user": user, "skills": _skills_sorted()},
    )


@router.get("/new")
async def competences_new_form(request: Request, user: AdminUser = Depends(require_admin)):
    return get_templates().TemplateResponse(
        request, "admin/competences/form.html",
        context={
            "user": user, "skill": None, "form_data": {}, "errors": {},
            "elements": ELEMENTS, "roles": ROLES, "kinds": KINDS,
        },
    )


def _read_form(fd: dict) -> tuple[str, dict, dict]:
    """Valide + construit (code, skill_dict, errors)."""
    errors: dict[str, str] = {}
    element = fd.get("element", "").strip()
    role = fd.get("role", "").strip()
    if element not in ELEMENTS:
        errors["element"] = "Élément invalide."
    if role not in ROLES:
        errors["role"] = "Rôle invalide."
    basic = content_sync.build_skill_effect(
        name=fd.get("basic_name", "").strip(),
        kind=fd.get("basic_kind", "damage").strip(),
        value=_parse_float(fd.get("basic_value"), 1.0),
        mana_cost=_parse_int(fd.get("basic_mana_cost"), 0),
    )
    special = content_sync.build_skill_effect(
        name=fd.get("special_name", "").strip(),
        kind=fd.get("special_kind", "damage").strip(),
        value=_parse_float(fd.get("special_value"), 1.5),
        mana_cost=_parse_int(fd.get("special_mana_cost"), 0),
        proc_chance=_parse_float(fd.get("special_proc_chance"), 0.1),
    )
    code = f"{element}_{role}"
    skill = content_sync.build_skill_dict(
        element=element, role=role, emoji=fd.get("emoji", "").strip(),
        basic=basic, special=special,
    )
    return code, skill, errors


@router.post("")
async def competences_create(request: Request, user: AdminUser = Depends(require_admin)):
    fd = {k: str(v) for k, v in (await request.form()).items()}
    code, skill, errors = _read_form(fd)
    element_skill_loader.clear_cache()
    if not errors and code in element_skill_loader.all_skills():
        errors["element"] = f"La compétence `{code}` existe déjà (éditez-la)."
    if errors:
        return get_templates().TemplateResponse(
            request, "admin/competences/form.html",
            context={
                "user": user, "skill": None, "form_data": fd, "errors": errors,
                "elements": ELEMENTS, "roles": ROLES, "kinds": KINDS,
            },
            status_code=400,
        )
    content_sync.upsert_skill_json(code, skill)
    _logger.info("Admin %s a créé la compétence %s", user.discord_id, code)
    return RedirectResponse("/admin/competences", status_code=303)


@router.get("/{code}/edit")
async def competences_edit_form(
    code: str, request: Request, user: AdminUser = Depends(require_admin),
):
    element_skill_loader.clear_cache()
    skill = element_skill_loader.get_skill(code)
    if skill is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Compétence `{code}` introuvable.")
    return get_templates().TemplateResponse(
        request, "admin/competences/form.html",
        context={
            "user": user, "skill": skill, "form_data": {}, "errors": {},
            "elements": ELEMENTS, "roles": ROLES, "kinds": KINDS,
        },
    )


@router.post("/{code}")
async def competences_update(
    code: str, request: Request, user: AdminUser = Depends(require_admin),
):
    fd = {k: str(v) for k, v in (await request.form()).items()}
    _, skill, errors = _read_form(fd)
    if errors:
        element_skill_loader.clear_cache()
        return get_templates().TemplateResponse(
            request, "admin/competences/form.html",
            context={
                "user": user, "skill": element_skill_loader.get_skill(code),
                "form_data": fd, "errors": errors,
                "elements": ELEMENTS, "roles": ROLES, "kinds": KINDS,
            },
            status_code=400,
        )
    # On garde le code d'origine (clé stable), on remplace son contenu.
    content_sync.upsert_skill_json(code, skill)
    _logger.info("Admin %s a édité la compétence %s", user.discord_id, code)
    return RedirectResponse("/admin/competences", status_code=303)


@router.post("/{code}/delete")
async def competences_delete(code: str, user: AdminUser = Depends(require_admin)):
    content_sync.delete_skill_json(code)
    _logger.info("Admin %s a supprimé la compétence %s", user.discord_id, code)
    return RedirectResponse("/admin/competences", status_code=303)
