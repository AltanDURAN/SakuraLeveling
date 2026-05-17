"""Routes admin pour gérer les shop_items (CRUD, avec DELETE car peu risqué)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request, status, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse

from app.infrastructure.db.repositories.item_repository import ItemRepository
from app.infrastructure.db.repositories.shop_repository import ShopRepository
from app.infrastructure.db.session import get_db_session
from webapp.admin.auth import AdminUser, require_admin


_logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin/shop", tags=["admin-shop"])


def get_templates():
    from webapp.main import templates
    return templates


def _parse_int(raw: str | None, default: int = 0) -> int:
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw.strip())
    except ValueError:
        return default


@router.get("", response_class=HTMLResponse)
async def shop_list(
    request: Request,
    user: AdminUser = Depends(require_admin),
    q: str | None = None,
    enabled: str | None = None,
):
    with get_db_session() as session:
        shop_items = ShopRepository(session).list_all(only_enabled=False)

    rows = []
    for si in shop_items:
        rows.append({
            "id": si.id,
            "item_code": si.item_definition.code,
            "item_name": si.item_definition.name,
            "category": si.item_definition.category,
            "buy_price": si.buy_price,
            "max_sell": si.max_sell_price,
            "min_sell": si.min_sell_price,
            "stock_threshold": si.stock_threshold,
            "current_stock": si.current_stock,
            "enabled": "✅" if si.enabled else "❌",
            "_enabled_raw": si.enabled,
        })

    if q:
        ql = q.lower()
        rows = [r for r in rows if ql in r["item_code"].lower() or ql in r["item_name"].lower()]
    if enabled == "1":
        rows = [r for r in rows if r["_enabled_raw"]]
    elif enabled == "0":
        rows = [r for r in rows if not r["_enabled_raw"]]

    return get_templates().TemplateResponse(
        request, "admin/shop/list.html",
        context={
            "user": user, "rows": rows,
            "filter_q": q or "",
            "filter_enabled": enabled or "",
        },
    )


@router.get("/new", response_class=HTMLResponse)
async def shop_new_form(
    request: Request,
    user: AdminUser = Depends(require_admin),
):
    with get_db_session() as session:
        all_items = ItemRepository(session).list_all()
        existing = {si.item_definition.code for si in ShopRepository(session).list_all()}
    available = [it for it in all_items if it.code not in existing]
    return get_templates().TemplateResponse(
        request, "admin/shop/form.html",
        context={
            "user": user, "shop_item": None, "errors": {},
            "available_items": available,
        },
    )


@router.post("")
async def shop_create(
    request: Request,
    user: AdminUser = Depends(require_admin),
):
    form = await request.form()
    fd = {k: str(v) for k, v in form.items()}
    errors: dict[str, str] = {}

    item_code = fd.get("item_code", "").strip()
    if not item_code:
        errors["item_code"] = "Item requis."

    if errors:
        with get_db_session() as session:
            all_items = ItemRepository(session).list_all()
            existing = {si.item_definition.code for si in ShopRepository(session).list_all()}
        return get_templates().TemplateResponse(
            request, "admin/shop/form.html",
            context={
                "user": user, "shop_item": None, "form_data": fd, "errors": errors,
                "available_items": [it for it in all_items if it.code not in existing],
            },
            status_code=400,
        )

    with get_db_session() as session:
        item = ItemRepository(session).get_by_code(item_code)
        if item is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Item `{item_code}` introuvable.")
        ShopRepository(session).create(
            item_definition_id=item.id,
            buy_price=_parse_int(fd.get("buy_price"), 0),
            max_sell_price=_parse_int(fd.get("max_sell_price"), 0),
            min_sell_price=_parse_int(fd.get("min_sell_price"), 0),
            stock_threshold=_parse_int(fd.get("stock_threshold"), 100),
            current_stock=_parse_int(fd.get("current_stock"), 0),
            enabled=fd.get("enabled") == "on",
        )

    return RedirectResponse(f"/admin/shop?q={item_code}", status_code=303)


@router.get("/{shop_item_id}/edit", response_class=HTMLResponse)
async def shop_edit_form(
    shop_item_id: int, request: Request,
    user: AdminUser = Depends(require_admin),
):
    with get_db_session() as session:
        items = {si.id: si for si in ShopRepository(session).list_all()}
    if shop_item_id not in items:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Shop item #{shop_item_id} introuvable.")
    return get_templates().TemplateResponse(
        request, "admin/shop/form.html",
        context={"user": user, "shop_item": items[shop_item_id], "errors": {}, "available_items": []},
    )


@router.post("/{shop_item_id}")
async def shop_update(
    shop_item_id: int, request: Request,
    user: AdminUser = Depends(require_admin),
):
    form = await request.form()
    fd = {k: str(v) for k, v in form.items()}
    with get_db_session() as session:
        repo = ShopRepository(session)
        result = repo.update(
            shop_item_id,
            buy_price=_parse_int(fd.get("buy_price"), 0),
            max_sell_price=_parse_int(fd.get("max_sell_price"), 0),
            min_sell_price=_parse_int(fd.get("min_sell_price"), 0),
            stock_threshold=_parse_int(fd.get("stock_threshold"), 100),
            enabled=fd.get("enabled") == "on",
        )
        if result is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Shop item #{shop_item_id} introuvable.")
        # Le current_stock se modifie via une API distincte côté repo
        if "current_stock" in fd:
            repo.set_stock(shop_item_id, _parse_int(fd.get("current_stock"), 0))
    return RedirectResponse(f"/admin/shop?q={result.item_definition.code}", status_code=303)


@router.post("/{shop_item_id}/delete")
async def shop_delete(
    shop_item_id: int,
    user: AdminUser = Depends(require_admin),
):
    with get_db_session() as session:
        ok = ShopRepository(session).delete(shop_item_id)
    if not ok:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Shop item #{shop_item_id} introuvable.")
    return RedirectResponse("/admin/shop", status_code=303)
