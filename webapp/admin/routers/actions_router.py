"""Routes admin : page d'actions rapides (give_gold, give_xp, set_level,
give_item, give_skill_points). Forme à formulaire qui exécute directement
sur la DB sans passer par Discord.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse

from app.infrastructure.db.repositories.item_repository import ItemRepository
from app.infrastructure.db.repositories.inventory_repository import (
    InventoryRepository,
)
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.session import get_db_session
from webapp.admin.auth import AdminUser, require_admin


_logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin/actions", tags=["admin-actions"])


def get_templates():
    from webapp.main import templates
    return templates


def _resolve_player_id(session, raw: str) -> int | None:
    """Accepte un Discord ID ou un username."""
    raw = (raw or "").strip()
    if not raw:
        return None
    repo = PlayerRepository(session)
    if raw.isdigit():
        profile = repo.get_by_discord_id(int(raw))
        if profile:
            return profile.player.id
    # fallback : search by username
    for p in repo.list_all_profiles():
        if p.player.username == raw or p.player.display_name == raw:
            return p.player.id
    return None


@router.get("", response_class=HTMLResponse)
async def actions_page(
    request: Request,
    user: AdminUser = Depends(require_admin),
    message: str | None = None,
    error: str | None = None,
):
    with get_db_session() as session:
        profiles = PlayerRepository(session).list_all_profiles()
        items = ItemRepository(session).list_all()

    return get_templates().TemplateResponse(
        request, "admin/actions.html",
        context={
            "user": user,
            "profiles": [
                {
                    "discord_id": p.player.discord_id,
                    "display_name": p.player.display_name,
                    "username": p.player.username,
                }
                for p in profiles
            ],
            "items": [{"code": it.code, "name": it.name} for it in items],
            "flash_message": message,
            "flash_error": error,
        },
    )


@router.post("/give_gold")
async def give_gold(
    request: Request,
    user: AdminUser = Depends(require_admin),
):
    form = await request.form()
    target = form.get("target", "")
    try:
        amount = int(form.get("amount", "0"))
    except ValueError:
        return RedirectResponse("/admin/actions?error=Montant+invalide", status_code=303)
    # 'give' = ajouter ; pour retirer/forcer un solde, utiliser set_gold (clamp ≥0).
    if amount < 0:
        return RedirectResponse(
            "/admin/actions?error=Montant+n%C3%A9gatif+refus%C3%A9+%E2%80%94+utilise+set_gold",
            status_code=303,
        )

    with get_db_session() as session:
        pid = _resolve_player_id(session, target)
        if pid is None:
            return RedirectResponse(f"/admin/actions?error=Joueur+%60{target}%60+introuvable", status_code=303)
        PlayerRepository(session).add_gold(pid, amount)
    _logger.info("Admin %s gave %d gold to player %s", user.discord_id, amount, target)
    return RedirectResponse(f"/admin/actions?message=%2B{amount}+or+ajout%C3%A9", status_code=303)


@router.post("/give_xp")
async def give_xp(
    request: Request,
    user: AdminUser = Depends(require_admin),
):
    form = await request.form()
    target = form.get("target", "")
    try:
        amount = int(form.get("amount", "0"))
    except ValueError:
        return RedirectResponse("/admin/actions?error=Montant+invalide", status_code=303)
    if amount < 0:
        return RedirectResponse(
            "/admin/actions?error=Montant+n%C3%A9gatif+refus%C3%A9",
            status_code=303,
        )

    with get_db_session() as session:
        pid = _resolve_player_id(session, target)
        if pid is None:
            return RedirectResponse(f"/admin/actions?error=Joueur+%60{target}%60+introuvable", status_code=303)
        PlayerRepository(session).add_xp(pid, amount)
    return RedirectResponse(f"/admin/actions?message=%2B{amount}+XP+ajout%C3%A9", status_code=303)


@router.post("/set_level")
async def set_level(
    request: Request,
    user: AdminUser = Depends(require_admin),
):
    form = await request.form()
    target = form.get("target", "")
    try:
        new_level = int(form.get("level", "0"))
        if new_level < 1:
            raise ValueError
    except ValueError:
        return RedirectResponse("/admin/actions?error=Niveau+invalide", status_code=303)

    with get_db_session() as session:
        repo = PlayerRepository(session)
        pid = _resolve_player_id(session, target)
        if pid is None:
            return RedirectResponse(f"/admin/actions?error=Joueur+%60{target}%60+introuvable", status_code=303)
        profile = repo.get_profile_by_player_id(pid)
        repo.apply_progression(
            player_id=pid,
            new_level=new_level,
            new_xp=0,
            new_skill_points=profile.progression.skill_points,
        )
    return RedirectResponse(f"/admin/actions?message=Niveau+r%C3%A9gl%C3%A9+%C3%A0+{new_level}", status_code=303)


@router.post("/give_skill_points")
async def give_skill_points(
    request: Request,
    user: AdminUser = Depends(require_admin),
):
    form = await request.form()
    target = form.get("target", "")
    try:
        amount = int(form.get("amount", "0"))
    except ValueError:
        return RedirectResponse("/admin/actions?error=Montant+invalide", status_code=303)

    with get_db_session() as session:
        pid = _resolve_player_id(session, target)
        if pid is None:
            return RedirectResponse(f"/admin/actions?error=Joueur+%60{target}%60+introuvable", status_code=303)
        PlayerRepository(session).add_skill_points(pid, amount)
    return RedirectResponse(f"/admin/actions?message=%2B{amount}+skill+points", status_code=303)


@router.post("/give_item")
async def give_item(
    request: Request,
    user: AdminUser = Depends(require_admin),
):
    form = await request.form()
    target = form.get("target", "")
    item_code = form.get("item_code", "").strip()
    try:
        qty = int(form.get("quantity", "1"))
        if qty < 1:
            raise ValueError
    except ValueError:
        return RedirectResponse("/admin/actions?error=Quantit%C3%A9+invalide", status_code=303)

    with get_db_session() as session:
        pid = _resolve_player_id(session, target)
        if pid is None:
            return RedirectResponse(f"/admin/actions?error=Joueur+%60{target}%60+introuvable", status_code=303)
        item = ItemRepository(session).get_by_code(item_code)
        if item is None:
            return RedirectResponse(f"/admin/actions?error=Item+%60{item_code}%60+introuvable", status_code=303)
        InventoryRepository(session).add_item(pid, item.id, qty)
    return RedirectResponse(
        f"/admin/actions?message=%2B{qty}+%C3%97+{item_code}+ajout%C3%A9",
        status_code=303,
    )
