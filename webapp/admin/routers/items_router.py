"""Routes admin pour gérer les items (CRUD, V1 sans delete)."""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse

from app.infrastructure.db.repositories.item_repository import ItemRepository
from app.infrastructure.db.session import get_db_session
from app.shared.enums import EquipmentSlot, FORGE_CATEGORIES, ItemCategory, ItemRarity
from webapp.admin.auth import AdminUser, require_admin


_logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/items", tags=["admin-items"])


# Stats supportées par le système (cf StatsService)
SUPPORTED_STATS = [
    "max_hp", "attack", "defense", "speed",
    "crit_chance", "crit_damage", "dodge", "hp_regeneration",
]


def get_templates():
    from webapp.main import templates
    return templates


def _parse_stat_bonuses(form_data: dict[str, str]) -> dict[str, int]:
    """Le form envoie stat_bonus_max_hp, stat_bonus_attack, etc.
    On extrait les non-zéros vers un dict propre."""
    out: dict[str, int] = {}
    for stat in SUPPORTED_STATS:
        raw = form_data.get(f"stat_bonus_{stat}", "").strip()
        if not raw:
            continue
        try:
            value = int(raw)
        except ValueError:
            continue
        if value != 0:
            out[stat] = value
    return out


def _common_form_context() -> dict:
    """Listes pour les <select> du formulaire."""
    return {
        "categories": [c.value for c in ItemCategory],
        "rarities": [r.value for r in ItemRarity],
        "slots": [None] + [s.value for s in EquipmentSlot],
        "supported_stats": SUPPORTED_STATS,
        "forge_categories": sorted(FORGE_CATEGORIES),
    }


@router.get("", response_class=HTMLResponse)
async def items_list(
    request: Request,
    user: AdminUser = Depends(require_admin),
    category: str | None = None,
    family: str | None = None,
    q: str | None = None,
):
    with get_db_session() as session:
        items = ItemRepository(session).list_all()

    # Filtres
    if category:
        items = [i for i in items if i.category == category]
    if family:
        items = [i for i in items if (i.family or "") == family]
    if q:
        q_lower = q.lower()
        items = [
            i for i in items
            if q_lower in i.code.lower() or q_lower in i.name.lower()
        ]

    items.sort(key=lambda i: (i.category, i.code))

    return get_templates().TemplateResponse(
        request, "admin/items/list.html",
        context={
            "user": user, "items": items,
            "filter_category": category or "",
            "filter_family": family or "",
            "filter_q": q or "",
            "all_categories": [c.value for c in ItemCategory],
            "all_families": sorted({i.family for i in items if i.family}),
        },
    )


@router.get("/new", response_class=HTMLResponse)
async def items_new_form(
    request: Request,
    user: AdminUser = Depends(require_admin),
):
    return get_templates().TemplateResponse(
        request, "admin/items/form.html",
        context={
            "user": user, "item": None,
            "stat_bonuses": {}, "errors": {},
            **_common_form_context(),
        },
    )


@router.post("")
async def items_create(
    request: Request,
    user: AdminUser = Depends(require_admin),
):
    form = await request.form()
    form_data = {k: str(v) for k, v in form.items()}
    errors: dict[str, str] = {}

    code = form_data.get("code", "").strip()
    name = form_data.get("name", "").strip()
    category = form_data.get("category", "").strip()
    if not code:
        errors["code"] = "Code requis."
    if not name:
        errors["name"] = "Nom requis."
    if category not in [c.value for c in ItemCategory]:
        errors["category"] = "Catégorie invalide."

    if errors:
        return get_templates().TemplateResponse(
            request, "admin/items/form.html",
            context={
                "user": user, "item": None,
                "form_data": form_data,
                "stat_bonuses": _parse_stat_bonuses(form_data),
                "errors": errors,
                **_common_form_context(),
            },
            status_code=400,
        )

    with get_db_session() as session:
        repo = ItemRepository(session)
        if repo.get_by_code(code) is not None:
            errors["code"] = f"Le code `{code}` existe déjà."
            return get_templates().TemplateResponse(
                request, "admin/items/form.html",
                context={
                    "user": user, "item": None,
                    "form_data": form_data,
                    "stat_bonuses": _parse_stat_bonuses(form_data),
                    "errors": errors,
                    **_common_form_context(),
                },
                status_code=400,
            )
        repo.create(
            code=code,
            name=name,
            description=form_data.get("description", "").strip(),
            category=category,
            rarity=form_data.get("rarity", "common").strip() or "common",
            stackable=form_data.get("stackable") == "on",
            max_stack=_parse_optional_int(form_data.get("max_stack")),
            sell_price=_parse_optional_int(form_data.get("sell_price")) or 0,
            buy_price=_parse_optional_int(form_data.get("buy_price")),
            icon=form_data.get("icon", "").strip() or None,
            stat_bonuses=_parse_stat_bonuses(form_data) or None,
            equipment_slot=form_data.get("equipment_slot", "").strip() or None,
            requires_two_hands=form_data.get("requires_two_hands") == "on",
            family=form_data.get("family", "").strip(),
        )

    return RedirectResponse(f"/admin/items?q={code}", status_code=303)


@router.get("/{code}/edit", response_class=HTMLResponse)
async def items_edit_form(
    code: str, request: Request,
    user: AdminUser = Depends(require_admin),
):
    with get_db_session() as session:
        item = ItemRepository(session).get_by_code(code)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Item `{code}` introuvable.")
    return get_templates().TemplateResponse(
        request, "admin/items/form.html",
        context={
            "user": user, "item": item,
            "stat_bonuses": item.stat_bonuses or {},
            "errors": {},
            **_common_form_context(),
        },
    )


@router.post("/{code}")
async def items_update(
    code: str, request: Request,
    user: AdminUser = Depends(require_admin),
):
    form = await request.form()
    form_data = {k: str(v) for k, v in form.items()}

    with get_db_session() as session:
        repo = ItemRepository(session)
        existing = repo.get_by_code(code)
        if existing is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, f"Item `{code}` introuvable.",
            )
        repo.update_by_code(
            code=code,
            name=form_data.get("name", existing.name),
            description=form_data.get("description", ""),
            category=form_data.get("category", existing.category),
            rarity=form_data.get("rarity", existing.rarity),
            stackable=form_data.get("stackable") == "on",
            max_stack=_parse_optional_int(form_data.get("max_stack")),
            sell_price=_parse_optional_int(form_data.get("sell_price")) or 0,
            buy_price=_parse_optional_int(form_data.get("buy_price")),
            icon=form_data.get("icon", "").strip() or None,
            stat_bonuses=_parse_stat_bonuses(form_data) or None,
            equipment_slot=form_data.get("equipment_slot", "").strip() or None,
            requires_two_hands=form_data.get("requires_two_hands") == "on",
            family=form_data.get("family", "").strip(),
        )
    return RedirectResponse(f"/admin/items?q={code}", status_code=303)


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
